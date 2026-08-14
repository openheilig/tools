/* filetrace.so -- log every write-mode file creation the engine attempts.
 *
 * Why: `---SAVING OK` is printed for a save that produces no file on disk
 * (2026-08-06, see REPORT.md).  There is no strace on this machine, and the
 * engine's own log never names the path it opened.  So interpose the two
 * calls that could create it and print the path + result.
 *
 * ponytail: write-mode only.  A full open() trace on this engine is tens of
 * thousands of lines of .pak reads and the interesting call is the one that
 * creates a file.  Reads are already covered by the cFile_ram breakpoints.
 *
 *   SACRED_PRELOAD=autopilot.so:filetrace.so ./play.sh
 *   (stderr; also honours SACRED_FT_ALL=1 to log read-mode opens too)
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <errno.h>
#include <stdarg.h>

static int want_all(void) {
    static int v = -1;
    if (v < 0) v = getenv("SACRED_FT_ALL") ? 1 : 0;
    return v;
}

FILE *fopen(const char *path, const char *mode) {
    static FILE *(*real)(const char *, const char *);
    if (!real) real = dlsym(RTLD_NEXT, "fopen");
    FILE *f = real(path, mode);
    /* The engine fopen()s its debug log in append mode once PER LOG LINE.
     * Tracing those is tens of thousands of stderr writes and slows the run
     * enough to desync autopilot's wall-clock script. */
    if (strstr(path, "log.txt")) return f;
    if (want_all() || strpbrk(mode, "wa+"))
        fprintf(stderr, "[ft] fopen(\"%s\",\"%s\") -> %p errno=%d %s\n",
                path, mode, (void *)f, f ? 0 : errno, f ? "" : strerror(errno));
    return f;
}

FILE *fopen64(const char *path, const char *mode) { return fopen(path, mode); }

int open(const char *path, int flags, ...) {
    static int (*real)(const char *, int, ...);
    if (!real) real = dlsym(RTLD_NEXT, "open");
    mode_t m = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); m = va_arg(ap, int); va_end(ap); }
    int fd = real(path, flags, m);
    if (want_all() || (flags & (O_WRONLY | O_RDWR | O_CREAT)))
        fprintf(stderr, "[ft] open(\"%s\",0%o) -> %d errno=%d %s\n",
                path, flags, fd, fd < 0 ? errno : 0, fd < 0 ? strerror(errno) : "");
    return fd;
}

int open64(const char *path, int flags, ...) {
    mode_t m = 0;
    if (flags & O_CREAT) { va_list ap; va_start(ap, flags); m = va_arg(ap, int); va_end(ap); }
    return open(path, flags, m);
}
