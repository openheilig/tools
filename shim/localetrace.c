/* Log every setlocale() call so the locale hypothesis can be tested rather
 * than assumed.  Without this, a clean run under LC_ALL=ru_RU proves nothing:
 * if nothing ever calls setlocale the process stays in "C" and the locale was
 * never actually applied.
 *
 *   gcc -m32 -shared -fPIC -o localetrace.so localetrace.c -ldl
 *   SACRED_PRELOAD=localetrace.so ./play.sh
 *
 * ponytail: stderr only, no formatting, no config.  It answers one question.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <locale.h>

/* Proves the interposer loaded.  Without it, "zero setlocale calls" is
 * ambiguous between "never called" and "preload silently didn't take". */
__attribute__((constructor)) static void hello(void)
{
    fprintf(stderr, "[localetrace] loaded\n"); fflush(stderr);
}

char *setlocale(int cat, const char *loc)
{
    static char *(*real)(int, const char *);
    if (!real) real = dlsym(RTLD_NEXT, "setlocale");
    char *r = real(cat, loc);
    /* cat 6 == LC_ALL on glibc; loc=="" is the environment-reading form. */
    fprintf(stderr, "[localetrace] setlocale(%d, %s) -> %s\n",
            cat, loc ? (loc[0] ? loc : "\"\"") : "NULL", r ? r : "NULL");
    fflush(stderr);
    return r;
}
