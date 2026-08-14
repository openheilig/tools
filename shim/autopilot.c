/* autopilot.so -- inject synthetic input into the engine from inside the process.
 *
 * Why this exists: the game cannot be driven from outside.  The host Xwayland
 * has no XTEST (so xdotool is useless), SDL_VIDEODRIVER=x11 stalls the engine
 * at dxDriver7::dxDriver7(), and GNOME denies screenshots -- so there is no
 * screen to look at and no way to click on it.  But `sacred` reads all input
 * through SDL_PollEvent, which is a dynamic import and therefore
 * LD_PRELOAD-interposable.  We fabricate events here instead.
 *
 * Feedback loop: the engine echoes console input to debug.log
 * ("CONSOLE INPUT: <%s>"), so the log is our eyes.
 *
 *   SACRED_AUTO="1000 key 96; 1500 text help; 1600 key 13"
 *   ms  action  args
 *       key   <sdlkey>      press+release
 *       click <x> <y>       move, button1 down, button1 up
 *       move  <x> <y>
 *       text  <chars>       one key per character (no spaces)
 *       wheel <4|5> <n>     SDL 1.2 wheel: 4 = up, 5 = down, n repeats
 *
 * ponytail: fixed 64-step script, no dynamic growth -- scripts are handwritten
 * and short; raise MAXSTEP if a real sequence ever needs more.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <signal.h>
#include <sys/time.h>
#include <ucontext.h>
#include <fcntl.h>
#include <unistd.h>

/* SDL 1.2 ABI (32-bit x86).  The engine allocates the SDL_Event on its own
 * stack using its 2005 headers, where sizeof(SDL_Event) == 20.  We must never
 * write past that or we smash the caller's frame. */
#define SDL_EVENT_SIZE 20
#define SDL_KEYDOWN            2
#define SDL_KEYUP              3
#define SDL_MOUSEMOTION        4
#define SDL_MOUSEBUTTONDOWN    5
#define SDL_MOUSEBUTTONUP      6
#define SDL_PRESSED            1
#define SDL_RELEASED           0

/* struct SDL_KeyboardEvent { u8 type,which,state; SDL_keysym keysym; }
 * SDL_keysym { u8 scancode; int sym; int mod; u16 unicode; }  -- keysym at +4 */
#define KEY_TYPE     0
#define KEY_WHICH    1
#define KEY_STATE    2
#define KEY_SCANCODE 4
#define KEY_SYM      8
#define KEY_MOD      12
#define KEY_UNICODE  16

/* struct SDL_MouseMotionEvent { u8 type,which,state; u16 x,y; s16 xrel,yrel; } */
#define MOT_TYPE  0
#define MOT_WHICH 1
#define MOT_STATE 2
#define MOT_X     4
#define MOT_Y     6
#define MOT_XREL  8
#define MOT_YREL  10

/* struct SDL_MouseButtonEvent { u8 type,which,button,state; u16 x,y; } */
#define BTN_TYPE   0
#define BTN_WHICH  1
#define BTN_BUTTON 2
#define BTN_STATE  3
#define BTN_X      4
#define BTN_Y      6

typedef int (*pollfn)(void *);
typedef unsigned char *(*getkeyfn)(int *);
typedef unsigned char (*getmousefn)(int *, int *);
static pollfn real_poll;
static getkeyfn real_getkey;
static getmousefn real_getmouse;

/* The engine POLLS input state as well as reading events (it imports
 * SDL_GetKeyState / SDL_GetMouseState), so events alone are ignored by the UI.
 * We therefore also hold synthetic keys/buttons "down" for HOLD_MS so a
 * state-polling frame sees them. */
#define HOLD_MS   150
#define NKEYS     512
static unsigned char kbuf[NKEYS];
static long          kexp[NKEYS];      /* ms (relative) until which key is held */
static long          btn_exp;
static int           have_synth_pos;

/* a fully-formed synthetic event, ready to memcpy into the caller's buffer */
struct ev { unsigned char b[SDL_EVENT_SIZE]; };

#define MAXQ 512
static struct ev q[MAXQ];
static int qhead, qtail;

#define MAXSTEP 1024
struct step { long ms; char act[8]; long a1, a2; char text[64]; int done; };
static struct step steps[MAXSTEP];
static int nsteps;

static void inj_note(int v);   /* fwd: defined with the selftest filter */
static int mouse_x = 400, mouse_y = 300;
static long t0_ms;
static FILE *input_log;
static int last_polled_x = -1, last_polled_y = -1, last_polled_buttons = -1;

static long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

static struct ev *qpush(void) {
    if ((qtail + 1) % MAXQ == qhead) return NULL;   /* full: drop */
    struct ev *e = &q[qtail];
    memset(e->b, 0, SDL_EVENT_SIZE);
    qtail = (qtail + 1) % MAXQ;
    return e;
}

static void put8(struct ev *e, int off, unsigned v) { e->b[off] = (unsigned char)v; }
static void put16(struct ev *e, int off, unsigned v) { unsigned short t = (unsigned short)v; memcpy(e->b + off, &t, 2); }
static void put32(struct ev *e, int off, unsigned v) { memcpy(e->b + off, &v, 4); }

/* ponytail: `key <sym> [scancode]`.  SDL 1.2's X11 driver fills .scancode with
 * the raw X keycode, and an engine that switches on scancode rather than .sym
 * ignores everything we send when it is 0 -- which is why `key 27` never
 * opened the in-game menu.  There is no portable sym->keycode map worth
 * writing here (X keycodes are layout-dependent and the letters are not
 * contiguous), so the script supplies it when it matters:
 *     60000 key 27 9        # Escape: X keycode 9 on a standard evdev layout
 * X keycode = evdev keycode + 8; `xev` or `showkey -s` gives the rest.
 * Omit it and you get the old scancode=0 behaviour, which is fine for
 * anything that reads .sym or SDL_GetKeyState. */
static int key_scancode;

static void emit_key(int sym, int down) {
    if (down && sym >= 0 && sym < NKEYS) kexp[sym] = now_ms() - t0_ms + HOLD_MS;
    struct ev *e = qpush();
    if (!e) return;
    put8(e, KEY_TYPE, down ? SDL_KEYDOWN : SDL_KEYUP);
    put8(e, KEY_WHICH, 0);
    put8(e, KEY_STATE, down ? SDL_PRESSED : SDL_RELEASED);
    put8(e, KEY_SCANCODE, (unsigned)key_scancode);
    put32(e, KEY_SYM, (unsigned)sym);
    put32(e, KEY_MOD, 0);
    /* engine calls SDL_EnableUNICODE, so text fields read .unicode.  Real
     * SDL 1.2 fills .unicode for control keys too (Return=13, Backspace=8,
     * Tab=9, Escape=27); the console's input line reads .unicode EXCLUSIVELY,
     * so a sym-only Enter was silently swallowed and commands never executed
     * (06-02 run t1tp, confirmed via missing CONSOLE INPUT echo). */
    put16(e, KEY_UNICODE, (down && ((sym >= 32 && sym < 127) ||
        sym == 13 || sym == 8 || sym == 9 || sym == 27)) ? (unsigned)sym : 0);
}

static void input_log_line(const char *kind, const char *detail) {
    if (!input_log) return;
    fprintf(input_log, "%ld\t%s\t%s\n", now_ms() - t0_ms, kind, detail);
    fflush(input_log);
}

static void emit_move(int x, int y) {
    char detail[96];
    snprintf(detail, sizeof(detail), "x=%d y=%d xrel=%d yrel=%d", x, y, x - mouse_x, y - mouse_y);
    input_log_line("synthetic-motion", detail);
    have_synth_pos = 1;
    struct ev *e = qpush();
    inj_note(x); inj_note(y);          /* provenance for the selftest filter */
    if (!e) { mouse_x = x; mouse_y = y; return; }
    put8(e, MOT_TYPE, SDL_MOUSEMOTION);
    put8(e, MOT_STATE, 0);
    put16(e, MOT_X, x);
    put16(e, MOT_Y, y);
    put16(e, MOT_XREL, (unsigned short)(short)(x - mouse_x));
    put16(e, MOT_YREL, (unsigned short)(short)(y - mouse_y));
    mouse_x = x; mouse_y = y;
}

static void emit_button_n(int x, int y, int down, int button) {
    char detail[96];
    snprintf(detail, sizeof(detail), "x=%d y=%d button=%d state=%s", x, y, button, down ? "down" : "up");
    input_log_line("synthetic-button", detail);
    /* button 4/5 are SDL 1.2's wheel up/down.  They are pressed and released
     * like any other button; the engine reads the wheel only as these events,
     * which is why zoom cannot be driven without them. */
    if (down && button == 1) btn_exp = now_ms() - t0_ms + HOLD_MS;
    struct ev *e = qpush();
    if (!e) return;
    put8(e, BTN_TYPE, down ? SDL_MOUSEBUTTONDOWN : SDL_MOUSEBUTTONUP);
    put8(e, BTN_WHICH, 0);
    put8(e, BTN_BUTTON, button);
    put8(e, BTN_STATE, down ? SDL_PRESSED : SDL_RELEASED);
    put16(e, BTN_X, x);
    put16(e, BTN_Y, y);
}

static void emit_button(int x, int y, int down) { emit_button_n(x, y, down, 1); }

static void parse_script(const char *s) {
    while (*s && nsteps < MAXSTEP) {
        while (*s == ' ' || *s == ';') s++;
        if (!*s) break;
        /* 06-02: segment FIRST, then parse inside it.  The old one-pass
         * sscanf let %15s swallow a bare action's terminating ';'
         * ("release;") and %95[^;] then ate the NEXT step into `rest` --
         * every argument-less `release` deleted the step after it (leg 1
         * lost a map toggle, t1leg0 lost one too, both saves failed). */
        const char *end = strchr(s, ';');
        size_t len = end ? (size_t)(end - s) : strlen(s);
        char seg[128];
        if (len >= sizeof(seg)) len = sizeof(seg) - 1;
        memcpy(seg, s, len);
        seg[len] = 0;
        struct step *st = &steps[nsteps];
        memset(st, 0, sizeof(*st));
        char act[16] = {0};
        int off = 0;
        if (sscanf(seg, "%ld %15s%n", &st->ms, act, &off) < 2) { s += len; continue; }
        const char *rest = seg + off;
        snprintf(st->act, sizeof(st->act), "%s", act);
        if (!strcmp(act, "text"))  sscanf(rest, " %63s", st->text);
        else                       sscanf(rest, "%ld %ld", &st->a1, &st->a2);
        nsteps++;
        s += len;
    }
    fprintf(stderr, "[autopilot] %d steps parsed\n", nsteps);
}

/* ---- EIP sampler ---------------------------------------------------------
 * yama ptrace_scope=1 here, so `gdb -p` on a running game is refused, and
 * driving the game *under* gdb fights with async-interrupt-in-batch-mode.
 * Sampling ourselves sidesteps both: SIGPROF fires on the busy thread, we
 * write the raw EIP, and objdump resolves it afterwards.
 *
 *   SACRED_PROF=1   -> /tmp/sacred-eip.bin  (stream of u32 EIPs @ ~100 Hz)
 *
 * ponytail: raw u32s + write(2) -- the only async-signal-safe option, and a
 * histogram is one awk away.
 */
static int prof_fd = -1;

/* The sampler is useless without the maps of the SAME process instance --
 * reading /proc/<pid>/maps from outside picked up a stale leftover `sacred`
 * once and sent the whole analysis into libGL's relocation table.  Dump our
 * own, from inside, after everything has loaded.  open/read/write are all
 * async-signal-safe. */
static void dump_maps(void) {
    int in = open("/proc/self/maps", O_RDONLY);
    if (in < 0) return;
    int out = open("/tmp/sacred-maps.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out >= 0) {
        char b[4096];
        ssize_t k;
        while ((k = read(in, b, sizeof(b))) > 0) { ssize_t w = write(out, b, k); (void)w; }
        close(out);
    }
    close(in);
}

static void prof_handler(int sig, siginfo_t *si, void *uc) {
    (void)sig; (void)si;
    static unsigned long nsamp;
    ucontext_t *c = uc;
    unsigned eip = (unsigned)c->uc_mcontext.gregs[REG_EIP];
    if (prof_fd >= 0) { ssize_t r = write(prof_fd, &eip, 4); (void)r; }
    if (++nsamp == 2000) dump_maps();      /* ~20 s of CPU in: all libs loaded */
}

static void input_log_init(void) {
    const char *path = getenv("SACRED_INPUT_LOG");
    if (!path || !*path) return;
    input_log = fopen(path, "w");
    if (input_log) {
        fprintf(input_log, "# monotonic_ms\tkind\tdetail\n");
        fflush(input_log);
    }
}

static void prof_init(void) {
    if (!getenv("SACRED_PROF")) return;
    prof_fd = open("/tmp/sacred-eip.bin", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (prof_fd < 0) return;
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = prof_handler;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigaction(SIGPROF, &sa, NULL);
    struct itimerval it = {{0, 10000}, {0, 10000}};   /* 100 Hz of CPU time */
    setitimer(ITIMER_PROF, &it, NULL);
    fprintf(stderr, "[autopilot] EIP sampler armed\n");
}

__attribute__((constructor))
static void init(void) {
    const char *s = getenv("SACRED_AUTO");
    if (s && *s) parse_script(s);
    t0_ms = now_ms();
    input_log_init();
    prof_init();
}

static void run_due(void) {
    long t = now_ms() - t0_ms;
    for (int i = 0; i < nsteps; i++) {
        struct step *st = &steps[i];
        if (st->done || t < st->ms) continue;
        st->done = 1;
        if (!strcmp(st->act, "key")) {
            key_scancode = (int)st->a2;
            emit_key((int)st->a1, 1);
            emit_key((int)st->a1, 0);
            key_scancode = 0;
        } else if (!strcmp(st->act, "text")) {
            for (const char *c = st->text; *c; c++) { emit_key(*c, 1); emit_key(*c, 0); }
        } else if (!strcmp(st->act, "move")) {
            emit_move((int)st->a1, (int)st->a2);
        } else if (!strcmp(st->act, "wheel")) {
            /* wheel <up|down count>: a1 = 4 (up) or 5 (down), a2 = repeats */
            for (long i = 0; i < (st->a2 > 0 ? st->a2 : 1); i++) {
                emit_button_n(mouse_x, mouse_y, 1, (int)st->a1);
                emit_button_n(mouse_x, mouse_y, 0, (int)st->a1);
            }
        } else if (!strcmp(st->act, "click")) {
            emit_move((int)st->a1, (int)st->a2);
            emit_button((int)st->a1, (int)st->a2, 1);
            emit_button((int)st->a1, (int)st->a2, 0);
        } else if (!strcmp(st->act, "hold")) {
            /* 06-02: hold <x> <y> / release -- keep button 1 down across many
             * frames so the engine re-paths toward the cursor every frame
             * (a single click's path can stall short of a door cell).  The
             * state-polling hold is pinned far out; `release` ends it. */
            emit_move((int)st->a1, (int)st->a2);
            btn_exp = now_ms() - t0_ms + 3600000L;
            struct ev *e = qpush();
            if (e) {
                put8(e, BTN_TYPE, SDL_MOUSEBUTTONDOWN);
                put8(e, BTN_WHICH, 0);
                put8(e, BTN_BUTTON, 1);
                put8(e, BTN_STATE, SDL_PRESSED);
                put16(e, BTN_X, (unsigned)st->a1);
                put16(e, BTN_Y, (unsigned)st->a2);
            }
        } else if (!strcmp(st->act, "down")) {
            /* 06-02: down <sym> [scancode] / up <sym> -- pin a key held
             * (like hold does for the mouse button) so the world map's
             * ALT+click teleport sees the modifier in the POLLED key state
             * while the click event lands.  `up` ends it. */
            int sym = (int)st->a1;
            key_scancode = (int)st->a2;
            emit_key(sym, 1);
            key_scancode = 0;
            if (sym >= 0 && sym < NKEYS)
                kexp[sym] = now_ms() - t0_ms + 3600000L;
        } else if (!strcmp(st->act, "up")) {
            int sym = (int)st->a1;
            if (sym >= 0 && sym < NKEYS) kexp[sym] = 0;
            emit_key(sym, 0);
        } else if (!strcmp(st->act, "release")) {
            btn_exp = 0;
            struct ev *e = qpush();
            if (e) {
                put8(e, BTN_TYPE, SDL_MOUSEBUTTONUP);
                put8(e, BTN_WHICH, 0);
                put8(e, BTN_BUTTON, 1);
                put8(e, BTN_STATE, SDL_RELEASED);
                put16(e, BTN_X, (unsigned)mouse_x);
                put16(e, BTN_Y, (unsigned)mouse_y);
            }
        }
        fprintf(stderr, "[autopilot] t=%ldms %s\n", t, st->act);
    }
}

/* Report the real video mode: click coordinates are in this space, and there is
 * no other way to learn it (GNOME denies screenshots, no X window to query). */
typedef void *(*setvideofn)(int, int, int, unsigned);
void *SDL_SetVideoMode(int w, int h, int bpp, unsigned flags) {
    static setvideofn real_svm;
    if (!real_svm) real_svm = (setvideofn)dlsym(RTLD_NEXT, "SDL_SetVideoMode");
    fprintf(stderr, "[autopilot] SDL_SetVideoMode %dx%d bpp=%d flags=0x%x\n", w, h, bpp, flags);
    return real_svm ? real_svm(w, h, bpp, flags) : NULL;
}

/* State-polling path: the UI reads SDL_GetKeyState/SDL_GetMouseState each
 * frame.  We merge synthetic held keys/buttons over the real state so real
 * input keeps working while a script runs. */
unsigned char *SDL_GetKeyState(int *numkeys) {
    if (!real_getkey) real_getkey = (getkeyfn)dlsym(RTLD_NEXT, "SDL_GetKeyState");
    int n = 0;
    unsigned char *r = real_getkey ? real_getkey(&n) : NULL;
    if (n <= 0 || n > NKEYS) n = 323;          /* SDLK_LAST in SDL 1.2 */
    run_due();
    if (r) memcpy(kbuf, r, n); else memset(kbuf, 0, n);
    long t = now_ms() - t0_ms;
    for (int i = 0; i < n; i++)
        if (kexp[i] > t) kbuf[i] = 1;
    if (numkeys) *numkeys = n;
    return kbuf;                                /* stable pointer: safe to cache */
}

unsigned char SDL_GetMouseState(int *x, int *y) {
    if (!real_getmouse) real_getmouse = (getmousefn)dlsym(RTLD_NEXT, "SDL_GetMouseState");
    int rx = 0, ry = 0;
    unsigned char b = real_getmouse ? real_getmouse(&rx, &ry) : 0;
    run_due();
    if (btn_exp > now_ms() - t0_ms) b |= 1;     /* SDL_BUTTON(1) */
    if (x) *x = have_synth_pos ? mouse_x : rx;
    if (y) *y = have_synth_pos ? mouse_y : ry;
    if (input_log && (rx != last_polled_x || ry != last_polled_y || b != (unsigned char)last_polled_buttons)) {
        char detail[128];
        snprintf(detail, sizeof(detail), "x=%d y=%d buttons=%u synthetic=%d", have_synth_pos ? mouse_x : rx, have_synth_pos ? mouse_y : ry, (unsigned)b, have_synth_pos);
        input_log_line("polled-mouse", detail);
        last_polled_x = rx;
        last_polled_y = ry;
        last_polled_buttons = b;
    }
    return b;
}

/* SDL 1.2 SDLMod bits (KMOD_LSHIFT=0x0001 ... KMOD_LALT=0x0100).  The world
 * map's ALT+click teleport reads the modifier through SDL_GetModState (or
 * SDL_GetKeyState's mod shadow), NOT through our per-key pinned state -- a
 * `down 308` without this hook is invisible to it (06-02 run t1tp2: cheats
 * confirmed active via CONSOLE echo, click landed on the map, no teleport). */
static int synth_mods(void) {
    long t = now_ms() - t0_ms;
    int m = 0;
    if (kexp[304] > t) m |= 0x0001;             /* LSHIFT */
    if (kexp[303] > t) m |= 0x0002;             /* RSHIFT */
    if (kexp[306] > t) m |= 0x0040;             /* LCTRL */
    if (kexp[305] > t) m |= 0x0080;             /* RCTRL */
    if (kexp[308] > t) m |= 0x0100;             /* LALT */
    if (kexp[309] > t) m |= 0x0200;             /* RALT */
    return m;
}

typedef int (*getmodfn)(void);
int SDL_GetModState(void) {
    static getmodfn real_getmod;
    if (!real_getmod) real_getmod = (getmodfn)dlsym(RTLD_NEXT, "SDL_GetModState");
    int m = real_getmod ? real_getmod() : 0;
    run_due();
    return m | synth_mods();
}

/* ---- framebuffer capture -------------------------------------------------
 * GNOME denies screenshots and there is no X window to grab, but the game
 * hands us its own frame: hook SDL_GL_SwapBuffers and glReadPixels the back
 * buffer just before it is presented.  This is the only way to SEE the menu,
 * and without it every click is a blind guess.
 *
 *   SACRED_SHOT="2000,8000,15000"   ms timestamps; writes /tmp/sacred-<ms>.ppm
 *
 * ponytail: PPM, not PNG -- 20 lines of stdio vs linking libpng, and any
 * viewer/converter reads it.
 */
#define GL_RGB           0x1907
#define GL_UNSIGNED_BYTE 0x1401
typedef void (*readpixfn)(int, int, int, int, unsigned, unsigned, void *);
typedef void (*swapfn)(void);

/* 06-02: raised 16 -> 64 -- a fire-frame series needs a 250 ms cadence
 * window (12-16 shots) plus settle frames plus a same-run control arm,
 * and retail runs are slow, so batching shots beats re-booting the game. */
#define MAXSHOT 64
static long shot_at[MAXSHOT];
static int  nshot, shot_done[MAXSHOT];
static int  shot_w = 1024, shot_h = 768;

static void shots_init(void) {
    const char *s = getenv("SACRED_SHOT");
    if (!s) return;
    while (*s && nshot < MAXSHOT) {
        char *end;
        long v = strtol(s, &end, 10);
        if (end == s) break;
        shot_at[nshot++] = v;
        s = (*end == ',') ? end + 1 : end;
    }
    fprintf(stderr, "[autopilot] %d screenshots scheduled\n", nshot);
}


/* ---- SACRED_DUMP: self memory snapshots -------------------------------
 *
 * Finding the hero's world position needs a differential scan: dump memory
 * while standing still, walk, dump again, and keep the words that moved.
 * gdb cannot do it here -- yama ptrace_scope=1 means only an ancestor may
 * ptrace, and gdb_run.sh exists for exactly that reason -- but this shim
 * already runs INSIDE the process, and a process may always read its own
 * /proc/self/mem with no ptrace at all. So the snapshot is taken from here,
 * on the same SwapBuffers clock the screenshots use.
 *
 *   SACRED_DUMP="20000,40000"   ms timestamps; writes /tmp/sacred-mem-<ms>.bin
 *                               plus a matching .map naming each region.
 *
 * Writable ANONYMOUS regions only: file-backed maps are code and read-only
 * data, and the stack moves for reasons that have nothing to do with the
 * player, so both are skipped to keep the diff's noise floor down.
 */
#define MAXDUMP 8
static long dump_at[MAXDUMP];
static int  ndump, dump_done[MAXDUMP];

static void dumps_init(void) {
    const char *s = getenv("SACRED_DUMP");
    if (!s) return;
    while (*s && ndump < MAXDUMP) {
        char *end;
        long v = strtol(s, &end, 10);
        if (end == s) break;
        dump_at[ndump++] = v;
        s = (*end == ',') ? end + 1 : end;
    }
    fprintf(stderr, "[autopilot] %d memory dumps scheduled\n", ndump);
}

static void memdump(long t) {
    char bp[64], mp[64];
    snprintf(bp, sizeof(bp), "/tmp/sacred-mem-%ld.bin", t);
    snprintf(mp, sizeof(mp), "/tmp/sacred-mem-%ld.map", t);
    FILE *maps = fopen("/proc/self/maps", "r");
    FILE *out = fopen(bp, "wb");
    FILE *idx = fopen(mp, "w");
    if (!maps || !out || !idx) { fprintf(stderr, "[autopilot] dump open failed\n"); return; }
    int fd = open("/proc/self/mem", O_RDONLY);
    if (fd < 0) { fprintf(stderr, "[autopilot] no /proc/self/mem\n"); return; }
    char line[512];
    unsigned long off = 0, total = 0;
    while (fgets(line, sizeof(line), maps)) {
        unsigned long a, b;
        char perm[8], rest[256];
        rest[0] = 0;
        if (sscanf(line, "%lx-%lx %7s %*s %*s %*s %255[^\n]", &a, &b, perm, rest) < 3) continue;
        if (perm[1] != 'w') continue;                /* writable only */
        if (rest[0] != 0 && rest[0] != ' ') continue; /* anonymous only */
        if (strstr(line, "[stack]") || strstr(line, "[vvar]") || strstr(line, "[vdso]")) continue;
        unsigned long len = b - a;
        if (len == 0 || len > (64UL << 20)) continue;
        char *buf = malloc(len);
        if (!buf) continue;
        ssize_t got = pread(fd, buf, len, (off_t)a);
        if (got > 0) {
            fwrite(buf, 1, (size_t)got, out);
            fprintf(idx, "%lx %lx %lu %lu\n", a, b, off, (unsigned long)got);
            off += (unsigned long)got;
            total += (unsigned long)got;
        }
        free(buf);
    }
    fclose(maps); fclose(out); fclose(idx); close(fd);
    fprintf(stderr, "[autopilot] memdump %ld: %lu bytes\n", t, total);
}


/* ---- SACRED_SELFTEST: in-process differential scan AND poke -------------
 *
 *   SACRED_SELFTEST="t1,t2,t3,delta"
 *
 * Snapshots the heap at t1/t2/t3 into its own memory, keeps the u32 words that
 * moved out and came back (the row 810 reversal filter), and then WRITES delta
 * into every survivor. If those words are the player position the character
 * teleports on the next frame, which is the causation test rows 807-810 could
 * only infer.
 *
 * WHY IN-PROCESS (row 808): heap CONTENTS are not reproducible across runs
 * even though the region base is, so an offset learned in one run addresses
 * something else in the next. The scan and the poke have to happen in the same
 * process life, which rules out gdb here as well -- ptrace_scope=1 means only
 * an ancestor may attach. This shim is already inside.
 */
/* Every coordinate this shim has injected. The engine keeps its own cursor,
 * which follows those events exactly -- so the cursor words move, reverse and
 * sit in cell range just like a player position, and they surfaced as
 * "candidates" in every scan (offsets 264-276 and 12564-12568). They are
 * excluded by IDENTITY, not by a guessed offset threshold: a value this shim
 * itself supplied cannot be evidence about the player. The earlier
 * "offset < 4096" guard was a guess and missed the copy at 12564. */
#define MAXINJ 256
static unsigned int inj[MAXINJ]; static int ninj;
static void inj_note(int v) {
    if (v < 0) return;
    for (int i = 0; i < ninj; i++) if (inj[i] == (unsigned)v) return;
    if (ninj < MAXINJ) inj[ninj++] = (unsigned)v;
}
static int inj_has(unsigned int v) {
    for (int i = 0; i < ninj; i++) if (inj[i] == v) return 1;
    return 0;
}

static long st_at[3] = {-1,-1,-1}; static long st_delta;
static int st_done[3];
static unsigned char *snap[3];
static unsigned long snap_len;

static void selftest_init(void) {
    const char *s = getenv("SACRED_SELFTEST");
    if (!s) return;
    char *e; int i;
    for (i = 0; i < 3; i++) { st_at[i] = strtol(s, &e, 10); if (*e != ',') { st_at[0] = -1; return; } s = e + 1; }
    st_delta = strtol(s, NULL, 10);
    fprintf(stderr, "[autopilot] selftest %ld,%ld,%ld delta=%ld\n", st_at[0], st_at[1], st_at[2], st_delta);
}

/* Same region rule memdump uses, so offsets mean the same thing. */
static unsigned char *heap_base(unsigned long *len) {
    FILE *maps = fopen("/proc/self/maps", "r"); if (!maps) return NULL;
    char line[512]; unsigned char *r = NULL;
    while (fgets(line, sizeof(line), maps)) {
        unsigned long a, b; char perm[8], rest[256]; rest[0] = 0;
        if (sscanf(line, "%lx-%lx %7s %*s %*s %*s %255[^\n]", &a, &b, perm, rest) < 3) continue;
        if (perm[1] != 'w') continue;
        if (rest[0] != 0 && rest[0] != ' ') continue;
        if (strstr(line, "[stack]") || strstr(line, "[vvar]") || strstr(line, "[vdso]")) continue;
        r = (unsigned char *)a; *len = b - a; break;
    }
    fclose(maps); return r;
}

static void selftest_step(int i) {
    unsigned long len = 0;
    unsigned char *base = heap_base(&len);
    if (!base) { fprintf(stderr, "[autopilot] selftest: no heap\n"); return; }
    if (i == 0) snap_len = len;
    if (len < snap_len) snap_len = len;
    snap[i] = malloc(snap_len);
    if (!snap[i]) return;
    memcpy(snap[i], base, snap_len);
    fprintf(stderr, "[autopilot] selftest snap %d: %lu bytes\n", i, snap_len);
    if (i != 2 || !snap[0] || !snap[1]) return;

    int poked = 0;
    for (unsigned long o = 0; o + 4 <= snap_len; o += 4) {
        unsigned int x, y, z;
        memcpy(&x, snap[0]+o, 4); memcpy(&y, snap[1]+o, 4); memcpy(&z, snap[2]+o, 4);
        if (!(x>64 && x<16384 && y>64 && y<16384 && z>64 && z<16384)) continue;
        long d1 = (long)y - (long)x, d2 = (long)z - (long)y;
        if (labs(d1) < 10 || labs(d2) < 10) continue;
        if ((d1 > 0) == (d2 > 0)) continue;
        /* the engine's cursor, echoing coordinates this shim injected */
        if (inj_has(x) || inj_has(y) || inj_has(z)) continue;
        unsigned int *p = (unsigned int *)(base + o);
        fprintf(stderr, "[autopilot] POKE +%lu: %u -> %ld\n", o, *p, (long)*p + st_delta);
        *p = (unsigned int)((long)*p + st_delta);
        poked++;
    }
    fprintf(stderr, "[autopilot] selftest poked %d words\n", poked);
}


/* ---- SACRED_WATCH: read the player cell at fixed times ------------------
 *   SACRED_WATCH="0x2a3b70:60000,180000,300000"
 * Prints the u32 PAIR at <first writable-anon region>+offset. Those words are
 * derived copies of the player position (row 812: they track it faithfully and
 * writing them does nothing), which reads perfectly well for navigation.
 * Unlike SACRED_SELFTEST this needs no direction reversal, so a ONE-WAY
 * traverse can finally report where it started, where it ended, and its rate --
 * row 813 spent nine minutes and could only say "the scenery changed".
 */
static unsigned long wt_off; static long wt_at[16]; static int wt_n, wt_done[16];
static void watch_init(void) {
    const char *s = getenv("SACRED_WATCH");
    if (!s) return;
    char *e;
    wt_off = strtoul(s, &e, 0); if (*e != ':') return;
    s = e + 1;
    while (*s && wt_n < 16) {
        long v = strtol(s, &e, 10); if (e == s) break;
        wt_at[wt_n++] = v; s = (*e == ',') ? e + 1 : e;
    }
    fprintf(stderr, "[autopilot] watch off=0x%lx x%d\n", wt_off, wt_n);
}
static void watch_now(long t) {
    unsigned long len = 0;
    unsigned char *base = heap_base(&len);
    if (!base || wt_off + 8 > len) return;
    unsigned int x, y;
    memcpy(&x, base + wt_off, 4); memcpy(&y, base + wt_off + 4, 4);
    fprintf(stderr, "[autopilot] WATCH t=%ld cell=%u,%u sector=%u,%u\n",
            t, x, y, x / 128, y / 128);
}

static void grab(long t) {
    static readpixfn rp;
    if (!rp) rp = (readpixfn)dlsym(RTLD_DEFAULT, "glReadPixels");
    if (!rp) { fprintf(stderr, "[autopilot] no glReadPixels\n"); return; }
    size_t n = (size_t)shot_w * shot_h * 3;
    unsigned char *buf = malloc(n);
    if (!buf) return;
    rp(0, 0, shot_w, shot_h, GL_RGB, GL_UNSIGNED_BYTE, buf);
    char path[64];
    snprintf(path, sizeof(path), "/tmp/sacred-%ld.ppm", t);
    FILE *f = fopen(path, "wb");
    if (f) {
        fprintf(f, "P6\n%d %d\n255\n", shot_w, shot_h);
        /* GL origin is bottom-left; PPM is top-down */
        for (int y = shot_h - 1; y >= 0; y--)
            fwrite(buf + (size_t)y * shot_w * 3, 1, (size_t)shot_w * 3, f);
        fclose(f);
        fprintf(stderr, "[autopilot] shot %s\n", path);
    }
    free(buf);
}

/* Frames since start, and at the previous shot -- the throughput measure the
 * ~1fps question needs (row 820). Incremented in the swap hook, which is by
 * definition once per presented frame, and reported at each SACRED_SHOT time
 * so an A/B reads straight off the log. */
static unsigned long frames, frames_prev;
static long fps_prev_t;

void SDL_GL_SwapBuffers(void) {
    static swapfn real_swap;
    static int inited;
    if (!inited) { inited = 1; shots_init(); dumps_init(); selftest_init(); watch_init(); }   /* lazy: avoids a fwd decl in init() */
    if (!real_swap) real_swap = (swapfn)dlsym(RTLD_NEXT, "SDL_GL_SwapBuffers");
    frames++;
    long t = now_ms() - t0_ms;
    for (int i = 0; i < nshot; i++)
        if (!shot_done[i] && t >= shot_at[i]) {
            shot_done[i] = 1;
            long dt = t - fps_prev_t;
            fprintf(stderr, "[autopilot] FPS t=%ld frames=%lu interval=%lu in %ldms => %.2f fps\n",
                    t, frames, frames - frames_prev, dt,
                    dt > 0 ? (double)(frames - frames_prev) * 1000.0 / (double)dt : 0.0);
            frames_prev = frames; fps_prev_t = t;
            grab(shot_at[i]);
        }
    for (int i = 0; i < wt_n; i++)
        if (!wt_done[i] && t >= wt_at[i]) { wt_done[i] = 1; watch_now(wt_at[i]); }
    for (int i = 0; i < 3; i++)
        if (st_at[i] >= 0 && !st_done[i] && t >= st_at[i]) { st_done[i] = 1; selftest_step(i); }
    for (int i = 0; i < ndump; i++)
        if (!dump_done[i] && t >= dump_at[i]) { dump_done[i] = 1; memdump(dump_at[i]); }
    if (real_swap) real_swap();
}

int SDL_PollEvent(void *event) {
    if (!real_poll) real_poll = (pollfn)dlsym(RTLD_NEXT, "SDL_PollEvent");
    if (real_poll) {
        int r = real_poll(event);
        if (r) {
            if (input_log && event) {
                unsigned char *b = event;
                char detail[160];
                if (b[0] == SDL_MOUSEMOTION) {
                    snprintf(detail, sizeof(detail), "type=%u x=%u y=%u xrel=%d yrel=%d state=%u", b[0], *(unsigned short *)(b + 4), *(unsigned short *)(b + 6), *(short *)(b + 8), *(short *)(b + 10), b[2]);
                } else if (b[0] == SDL_MOUSEBUTTONDOWN || b[0] == SDL_MOUSEBUTTONUP) {
                    snprintf(detail, sizeof(detail), "type=%u x=%u y=%u button=%u state=%u", b[0], *(unsigned short *)(b + 4), *(unsigned short *)(b + 6), b[2], b[3]);
                } else if (b[0] == SDL_KEYDOWN || b[0] == SDL_KEYUP) {
                    snprintf(detail, sizeof(detail), "type=%u sym=%d scancode=%u state=%u unicode=%u", b[0], *(int *)(b + KEY_SYM), b[KEY_SCANCODE], b[KEY_STATE], *(unsigned short *)(b + KEY_UNICODE));
                } else {
                    snprintf(detail, sizeof(detail), "type=%u", b[0]);
                }
                input_log_line("real-event", detail);
            }
            return r;          /* real input always wins */
        }
    }
    run_due();
    if (qhead != qtail && event) {
        memcpy(event, q[qhead].b, SDL_EVENT_SIZE);
        if (input_log) {
            unsigned char *b = q[qhead].b;
            char detail[160];
            if (b[0] == SDL_MOUSEMOTION) {
                snprintf(detail, sizeof(detail), "type=%u x=%u y=%u xrel=%d yrel=%d state=%u", b[0], *(unsigned short *)(b + 4), *(unsigned short *)(b + 6), *(short *)(b + 8), *(short *)(b + 10), b[2]);
            } else if (b[0] == SDL_MOUSEBUTTONDOWN || b[0] == SDL_MOUSEBUTTONUP) {
                snprintf(detail, sizeof(detail), "type=%u x=%u y=%u button=%u state=%u", b[0], *(unsigned short *)(b + 4), *(unsigned short *)(b + 6), b[2], b[3]);
            } else if (b[0] == SDL_KEYDOWN || b[0] == SDL_KEYUP) {
                snprintf(detail, sizeof(detail), "type=%u sym=%d scancode=%u state=%u unicode=%u", b[0], *(int *)(b + KEY_SYM), b[KEY_SCANCODE], b[KEY_STATE], *(unsigned short *)(b + KEY_UNICODE));
            } else {
                snprintf(detail, sizeof(detail), "type=%u", b[0]);
            }
            input_log_line("synthetic-event", detail);
        }
        qhead = (qhead + 1) % MAXQ;
        return 1;
    }
    return 0;
}
