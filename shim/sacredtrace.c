/* sacredtrace -- LD_PRELOAD interposer for the stripped 32-bit `sacred` binary.
 *
 * Why this and not TSAN/helgrind: the target is a stripped, closed, 32-bit ELF.
 * TSAN needs recompilation; helgrind on a 2005 binary is unusably slow. But every
 * sync primitive the engine uses is a *dynamic import* (verified: 16 pthread/sem
 * symbols in the PLT, and notably NO pthread_cond_* at all), so plain symbol
 * interposition sees all of it.
 *
 * The hypothesis this is built to test: the engine polls sem_getvalue() and
 * proceeds regardless of the result, so an async table load that has not landed
 * yields a zeroed eItemType -> `cCreatureHero::CalcResults () type=0 FAILED!`.
 *
 * Build (must be 32-bit to match the target):
 *     gcc -m32 -shared -fPIC -O2 -o sacredtrace.so sacredtrace.c -ldl -lpthread
 *
 * Run -- NOTE the project path contains a space and LD_PRELOAD splits on spaces
 * with no escaping mechanism, so an absolute path here CANNOT work. Copy the .so
 * next to the binary and preload it relatively:
 *     cp sacredtrace.so ../../install/ && cd ../../install
 *     SACREDTRACE=sem,thread ST_LOG=/tmp/st.log \
 *     LD_PRELOAD=./sacredtrace.so ./sacred --nosound
 *
 * SACREDTRACE selects categories (comma-separated, default "sem,thread"):
 *     sem     sem_init/wait/post/getvalue     <- the interesting one
 *     mutex   pthread_mutex_lock/unlock       <- very high volume
 *     thread  pthread_create/join
 *     io      open/read/fopen/fread
 * ST_LOG defaults to stderr.
 *
 * ponytail: line-oriented text log, no ring buffer, no binary format. The volume
 * is fine for sem+thread; add buffering only if `mutex` or `io` proves too slow.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

enum { C_SEM = 1, C_MUTEX = 2, C_THREAD = 4, C_IO = 8, C_GTK = 16 };

static int cats = C_SEM | C_THREAD;
static FILE *out;
static pthread_mutex_t out_lk = PTHREAD_MUTEX_INITIALIZER;

/* Resolve lazily: calling dlsym() from a constructor can recurse through
 * malloc on some libcs. Each wrapper resolves its own next-pointer once. */
#define NEXT(fn, ret, ...)                                                     \
    typedef ret (*fn##_fp)(__VA_ARGS__);                                       \
    static fn##_fp next_##fn;                                                  \
    if (!next_##fn) next_##fn = (fn##_fp)dlsym(RTLD_NEXT, #fn)

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

__attribute__((constructor)) static void st_init(void)
{
    const char *c = getenv("SACREDTRACE");
    const char *p = getenv("ST_LOG");
    if (c) {
        cats = 0;
        if (strstr(c, "sem"))    cats |= C_SEM;
        if (strstr(c, "mutex"))  cats |= C_MUTEX;
        if (strstr(c, "thread")) cats |= C_THREAD;
        if (strstr(c, "io"))     cats |= C_IO;
        if (strstr(c, "gtk"))    cats |= C_GTK;
    }
    /* fopen() is interposed below and can call ev() while this constructor
     * opens ST_LOG. Seed the sink first so that early loader I/O cannot write
     * through a NULL FILE*. */
    out = stderr;
    if (p) {
        FILE *log = fopen(p, "w");
        if (log) out = log;
    }
    setvbuf(out, NULL, _IOLBF, 0);
}

static void ev(int cat, const char *fmt, ...)
{
    if (!(cats & cat)) return;
    va_list ap;
    va_start(ap, fmt);
    pthread_mutex_lock(&out_lk);
    fprintf(out, "%10.3f t%ld ", now_ms(), (long)syscall(SYS_gettid));
    vfprintf(out, fmt, ap);
    fputc('\n', out);
    pthread_mutex_unlock(&out_lk);
    va_end(ap);
}

/* --- semaphores: the primary suspect ---------------------------------- */

int sem_init(sem_t *s, int pshared, unsigned value)
{
    NEXT(sem_init, int, sem_t *, int, unsigned);
    ev(C_SEM, "sem_init   %p val=%u", (void *)s, value);
    return next_sem_init(s, pshared, value);
}

int sem_wait(sem_t *s)
{
    NEXT(sem_wait, int, sem_t *);
    double t0 = now_ms();
    int r = next_sem_wait(s);
    double d = now_ms() - t0;
    /* A wait that blocks is the engine correctly synchronising. A wait that
     * returns instantly every time means the semaphore is always already
     * posted -- i.e. it is not actually gating anything. */
    ev(C_SEM, "sem_wait   %p %s waited=%.3fms", (void *)s,
       d > 0.05 ? "BLOCKED" : "nowait", d);
    return r;
}

int sem_post(sem_t *s)
{
    NEXT(sem_post, int, sem_t *);
    ev(C_SEM, "sem_post   %p", (void *)s);
    return next_sem_post(s);
}

int sem_getvalue(sem_t *s, int *val)
{
    NEXT(sem_getvalue, int, sem_t *, int *);
    int r = next_sem_getvalue(s, val);
    /* THE hypothesis: value==0 here means "work not finished". If the engine
     * polls this, sees 0, and carries on anyway, the next creature it builds
     * gets a zeroed type. Correlate these lines against `type=0 FAILED!`. */
    ev(C_SEM, "sem_getval %p -> %d%s", (void *)s, val ? *val : -1,
       (val && *val == 0) ? "   <== NOT READY" : "");
    return r;
}

/* --- threads ---------------------------------------------------------- */

int pthread_create(pthread_t *th, const pthread_attr_t *attr,
                   void *(*fn)(void *), void *arg)
{
    NEXT(pthread_create, int, pthread_t *, const pthread_attr_t *,
         void *(*)(void *), void *);
    /* Name the module owning the start routine. Without this a burst of
     * identical threads is ambiguous: the game's loaders and llvmpipe's
     * worker pool look exactly the same in the log. */
    Dl_info di;
    const char *mod = (dladdr((void *)fn, &di) && di.dli_fname) ? di.dli_fname : "?";
    ev(C_THREAD, "thr_create start=%p arg=%p mod=%s", (void *)fn, arg, mod);
    return next_pthread_create(th, attr, fn, arg);
}

int pthread_join(pthread_t th, void **ret)
{
    NEXT(pthread_join, int, pthread_t, void **);
    ev(C_THREAD, "thr_join");
    return next_pthread_join(th, ret);
}

/* --- mutexes (high volume; opt in) ------------------------------------ */

int pthread_mutex_lock(pthread_mutex_t *m)
{
    NEXT(pthread_mutex_lock, int, pthread_mutex_t *);
    if (!(cats & C_MUTEX)) return next_pthread_mutex_lock(m);
    double t0 = now_ms();
    int r = next_pthread_mutex_lock(m);
    double d = now_ms() - t0;
    if (d > 0.05) ev(C_MUTEX, "mtx_lock   %p CONTENDED %.3fms", (void *)m, d);
    return r;
}

int pthread_mutex_unlock(pthread_mutex_t *m)
{
    NEXT(pthread_mutex_unlock, int, pthread_mutex_t *);
    return next_pthread_mutex_unlock(m);
}

/* --- gtk: locate the LGP security dialog's construction site ----------
 * The dialog text is not a plaintext string anywhere in the binary, so the
 * only way to find the check is to catch it building the widget. Logging the
 * caller's offset within `sacred` gives an address to disassemble directly.
 */
static void log_caller(const char *what, const char *text, void *ra)
{
    Dl_info di;
    if (dladdr(ra, &di) && di.dli_fbase)
        ev(C_GTK, "%s \"%s\" ra=%p %s+0x%lx", what, text ? text : "(null)", ra,
           di.dli_fname ? di.dli_fname : "?",
           (unsigned long)((char *)ra - (char *)di.dli_fbase));
    else
        ev(C_GTK, "%s \"%s\" ra=%p", what, text ? text : "(null)", ra);
}

void *gtk_label_new(const char *str)
{
    NEXT(gtk_label_new, void *, const char *);
    log_caller("gtk_label_new", str, __builtin_return_address(0));
    return next_gtk_label_new(str);
}

void gtk_label_set_text(void *label, const char *str)
{
    NEXT(gtk_label_set_text, void, void *, const char *);
    log_caller("gtk_label_set", str, __builtin_return_address(0));
    next_gtk_label_set_text(label, str);
}

/* --- file I/O: correlate async loads with the sem traffic -------------- */

FILE *fopen(const char *path, const char *mode)
{
    NEXT(fopen, FILE *, const char *, const char *);
    FILE *f = next_fopen(path, mode);
    ev(C_IO, "fopen      %s -> %p", path, (void *)f);
    return f;
}

size_t fread(void *buf, size_t sz, size_t n, FILE *f)
{
    NEXT(fread, size_t, void *, size_t, size_t, FILE *);
    double t0 = now_ms();
    size_t r = next_fread(buf, sz, n, f);
    ev(C_IO, "fread      %p %zu bytes %.3fms", (void *)f, r * sz, now_ms() - t0);
    return r;
}
