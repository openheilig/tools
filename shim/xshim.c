/* Shims for running the 2005 LGP Sacred binary on a modern 64-bit system. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <malloc.h>

extern void __libc_free(void *ptr);
extern void *__libc_malloc(size_t size);
extern void *__libc_calloc(size_t n, size_t size);
extern void *__libc_realloc(void *ptr, size_t size);

/* _XGetRequest: missing from the bundled 2007 (etch) libX11; referenced by
 * glvnd's libGLX when libGL.so.1 is preloaded to put GL symbols into the
 * global scope for the game's dlsym(0, ...) resolver. Never actually
 * called on this stack (rendering goes through SDL3's EGL/Wayland path). */
void *_XGetRequest(void *dpy, unsigned char opcode, unsigned long len) {
    (void)dpy; (void)opcode; (void)len;
    return 0;
}

/* The engine's "free pixels after texture upload" cleanup path sometimes
 * frees a pointer that was never allocated (or was already freed): its
 * texture-record teardown misreads a field when a texture failed to load.
 * 2005 glibc let that slide; modern glibc aborts inside free(), and the
 * LGP crash handler then deadlocks trying to report it.
 *
 * Track live allocations in an open-addressing set and only forward frees
 * of pointers we know are live. Bogus and duplicate frees are dropped.
 *
 * Sizing matters: at HT_BITS 17 (131072 slots) the table filled during world
 * load and ht_insert's probe loop -- which had no full-table check -- spun
 * forever.  That was the hang at "Reading Questbinary": 100% of CPU samples
 * landed on the 4-instruction probe loop at xshim.so+0x1220 (found 2026-08-06
 * with autopilot.so's SIGPROF sampler).  22 bits = 4M slots = 16 MB of BSS,
 * comfortably above the engine's live-allocation peak. */

/* Overridable at build time so the pre-fix size can be reproduced for a
 * controlled experiment:  gcc -DHT_BITS=17 ...  (see analysis/) */
#ifndef HT_BITS
#define HT_BITS 22
#endif
#define HT_SIZE (1u << HT_BITS)
#define HT_EMPTY 0
#define HT_DEAD  1

static uintptr_t ht[HT_SIZE];
static volatile int ht_lock;
static unsigned ht_live, ht_peak;
static int ht_full;             /* table overflowed: stop pretending we track */
static unsigned n_foreign, n_nocopy;   /* realloc of an untracked pointer / of one we dared not copy */
/* Frees we swallowed because the pointer was not in the live set.  Every one of
 * these is either the 2005 bogus free we exist to absorb, or a pointer glibc
 * allocated through an internal call that never reached our malloc (strdup,
 * getline, asprintf ...) -- in which case we are leaking it.  Counting them is
 * how we tell those two apart. */
static unsigned n_dropped;

/* XSHIM_NOTRACK=1 -> malloc/free/realloc pass straight through to glibc, with
 * only the zeroing kept.  This is the control arm: it removes the live-set
 * entirely, so any behaviour that survives it is the engine's, not ours.
 * Expect the 2005 double-free to abort somewhere; that is the point of the
 * tracking and is itself a datum. */
static int notrack = -1;
static inline int no_track(void) {
    /* Empty string counts as unset.  `env XSHIM_NOTRACK= ./play.sh` reads as
     * "set" to getenv, which silently turned the control arm of an A/B into a
     * second copy of the test arm.  Cost an hour on 2026-08-06. */
    if (notrack < 0) { const char *e = getenv("XSHIM_NOTRACK"); notrack = (e && *e) ? 1 : 0; }
    return notrack;
}

static int stats_on = -1;
static inline int getenv_stats(void) {
    if (stats_on < 0) { const char *e = getenv("XSHIM_STATS"); stats_on = (e && *e) ? 1 : 0; }
    return stats_on;
}

/* XSHIM_NOLOCK=1 makes these no-ops (row 820). The live-set itself is
 * LOAD-BEARING -- XSHIM_NOTRACK=1 aborts on the 2005 double-free in under 45s
 * (row 819) -- but the LOCK around it may not be: this engine is
 * single-threaded on this stack, so every malloc and free pays an atomic
 * read-modify-write that nothing ever contends. Unlike NOTRACK this keeps the
 * hash table intact, so it cannot reintroduce the double-free; if it changes
 * nothing the cost is the table, not the lock, and XSHIM_STATS measures that. */
static int nolock = -1;
static inline int no_lock(void) {
    /* empty string counts as unset, same trap the NOTRACK comment records */
    if (nolock < 0) { const char *e = getenv("XSHIM_NOLOCK"); nolock = (e && *e) ? 1 : 0; }
    return nolock;
}
static inline void lock(void)   { if (no_lock()) return; while (__sync_lock_test_and_set(&ht_lock, 1)) {} }
static inline void unlock(void) { if (no_lock()) return; __sync_lock_release(&ht_lock); }

static unsigned hash(uintptr_t p) { return (unsigned)((p >> 4) * 2654435761u) >> (32 - HT_BITS); }

/* Give up after this many probes.  At the shipped 22 bits the peak load is
 * ~154k live in 4M slots (3.7%), where a 64-long cluster is not a thing that
 * happens; the cap only ever fires on a table that is already pathological.
 *
 * Capping is not optional.  Bounding the probe at HT_SIZE, as the first fix
 * did, is not enough: 131072 probes on *every* malloc is a livelock in all
 * but name.  Measured 2026-08-06 with a -DHT_BITS=17 build -- State R, 77%
 * CPU, RSS flat at 278 MB, wedged at `Reading Questbinary` indefinitely.
 * Indistinguishable from the original infinite spin from the outside. */
#define HT_PROBE_MAX 64

static void ht_insert(uintptr_t p) {
    unsigned i = hash(p);
    for (unsigned n = 0; n < HT_PROBE_MAX; n++) {
        if (ht[i] <= HT_DEAD) {
            ht[i] = p;
            if (++ht_live > ht_peak) ht_peak = ht_live;
            return;
        }
        i = (i + 1) & (HT_SIZE - 1);
    }
    ht_full = 1;    /* stop pretending we track; see free() */
}

/* 1 = was live (now marked dead), 0 = definitely absent (hit an empty slot),
 * -1 = gave up after HT_PROBE_MAX.
 *
 * The old version was `while (ht[i] != HT_EMPTY)`, which on a table with no
 * empty slot left never terminates.  That -- not ht_insert -- is what wedged
 * the 17-bit build even after ht_insert had been bounded. */
static int ht_remove(uintptr_t p) {
    unsigned i = hash(p);
    for (unsigned n = 0; n < HT_PROBE_MAX; n++) {
        if (ht[i] == HT_EMPTY) return 0;
        if (ht[i] == p) { ht[i] = HT_DEAD; ht_live--; return 1; }
        i = (i + 1) & (HT_SIZE - 1);
    }
    return -1;
}

/* The destructor never runs on the runs we care about -- they end in SIGKILL
 * from the harness or in address-space exhaustion -- so XSHIM_STATS also dumps
 * every 2^20 mallocs.  That is the only way to read the counters out of a
 * process that is going to be killed. */
static void stats_dump(const char *why);

void *malloc(size_t size) {
    if (__builtin_expect(getenv_stats(), 0)) {
        static unsigned long n;
        if (((++n) & 0xFFFFFu) == 0) stats_dump("tick");
    }
    void *p = __libc_malloc(size);
    if (p) {
        /* 2005 glibc often handed out zeroed fresh pages; some engine
         * parsers implicitly rely on that. Modern glibc recycles dirty
         * arena memory. Zero every allocation. */
        memset(p, 0, size);
        if (!no_track()) { lock(); ht_insert((uintptr_t)p); unlock(); }
    }
    return p;
}

void *calloc(size_t n, size_t size) {
    void *p = __libc_calloc(n, size);
    if (p && !no_track()) { lock(); ht_insert((uintptr_t)p); unlock(); }
    return p;
}

/* Every allocator that can hand the engine a pointer it will later free must be
 * tracked, or free() drops that pointer and we leak it.  Interposing only
 * malloc/calloc/realloc left ~15% of all frees untracked -- measured 1,250,111
 * dropped frees in 95 s, ~1 KB each, which is the entire ~13 MB/s leak.
 * strdup and friends are the usual suspects: glibc resolves its internal
 * malloc call directly, so the memory never passes through ours. */
extern void *__libc_memalign(size_t align, size_t size);

static void *track(void *p) {
    if (p && !no_track()) { lock(); ht_insert((uintptr_t)p); unlock(); }
    return p;
}

void *memalign(size_t align, size_t size)      { return track(__libc_memalign(align, size)); }
void *aligned_alloc(size_t align, size_t size) { return track(__libc_memalign(align, size)); }
void *valloc(size_t size)                      { return track(__libc_memalign(4096, size)); }

int posix_memalign(void **out, size_t align, size_t size) {
    void *p = __libc_memalign(align, size);
    if (!p) return 12 /* ENOMEM */;
    *out = track(p);
    return 0;
}

/* Built on our own malloc so the result is tracked and zeroed like any other. */
char *strdup(const char *s) {
    size_t n = strlen(s) + 1;
    char *p = malloc(n);
    if (p) memcpy(p, s, n);
    return p;
}

char *strndup(const char *s, size_t max) {
    size_t n = strnlen(s, max);
    char *p = malloc(n + 1);
    if (p) { memcpy(p, s, n); p[n] = 0; }
    return p;
}

void *realloc(void *ptr, size_t size) {
    if (!ptr) return malloc(size);
    if (no_track()) return __libc_realloc(ptr, size);
    lock();
    int was_live = ht_remove((uintptr_t)ptr);
    unlock();
    /* != 1, so "gave up probing" (-1) lands here too: if we are not certain we
     * own the pointer, never hand it to __libc_realloc. */
    if (was_live != 1) {
        /* Foreign pointer: don't hand it to __libc_realloc (it may not be
         * ours), but DO copy the contents.  Returning a fresh buffer silently
         * discards the caller's data, and since malloc() zeroes, the engine
         * would read its own structs back as zeros.
         *
         * That was once the leading suspect for "CalcResults () type=0
         * FAILED" -- it is not.  Falsified 2026-08-06 by an A/B on
         * XSHIM_NOCOPY at HT_BITS=17: copy on and copy off are
         * indistinguishable, 3/3 runs each.  Copying is still the correct
         * thing to do here; it just is not the cause of that log line.
         * malloc_usable_size gives the old size for any glibc pointer. */
        void *p = malloc(size);
        if (p) {
            /* Only trust usable_size when it looks like a real glibc chunk --
             * a pointer from a foreign allocator has no chunk header at -8 and
             * would yield a garbage length, turning silent data loss into a
             * segfault.  Implausible -> copy nothing (the old behaviour). */
            /* XSHIM_NOCOPY=1 reproduces the pre-fix behaviour on purpose.
             * Kept because it is the control arm for the experiment above. */
            static int nocopy = -1;
            if (nocopy < 0) nocopy = getenv("XSHIM_NOCOPY") ? 1 : 0;
            size_t old = nocopy ? 0 : malloc_usable_size(ptr);
            if (old && old <= (64u << 20)) memcpy(p, ptr, old < size ? old : size);
            else n_nocopy++;
        }
        n_foreign++;
        return p;
    }
    void *p = __libc_realloc(ptr, size);
    if (p) { lock(); ht_insert((uintptr_t)p); unlock(); }
    return p;
}

void free(void *ptr) {
    if (!ptr) return;
    if (no_track()) { __libc_free(ptr); return; }
    lock();
    int live = ht_remove((uintptr_t)ptr);
    int full = ht_full;
    unlock();
    /* Once the table has overflowed we can no longer tell a bogus free from an
     * untracked one, and dropping real frees would leak without bound.  Fall
     * back to 2005 behaviour -- the double-free abort is a risk, an OOM is a
     * certainty.  live == -1 (probe gave up) is treated the same way and is
     * why ht_remove's cap cannot leak: unsure always means forward. */
    if (live != 0 || full) __libc_free(ptr);
    else n_dropped++;
}

/* Peak live-allocation count, so the table can be sized on evidence rather
 * than guesswork:  XSHIM_STATS=1 ./play.sh */
static void stats_dump(const char *why) {
    fprintf(stderr, "[xshim %s] live=%u peak=%u of %u slots%s  "
                    "foreign-realloc=%u uncopied=%u dropped-frees=%u\n",
            why, ht_live, ht_peak, HT_SIZE, ht_full ? " TABLE-OVERFLOWED" : "",
            n_foreign, n_nocopy, n_dropped);
}

__attribute__((destructor))
static void xshim_stats(void) { if (getenv_stats()) stats_dump("exit"); }
