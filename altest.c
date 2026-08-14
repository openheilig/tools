/* altest -- can the bundled OpenAL open an output device on this machine?
 *
 * The game reaches gameplay with sound enabled and produces ZERO PulseAudio
 * sink-inputs (2026-08-06).  The engine's log says nothing about audio beyond
 * `cSoundChunk 128`, so there is no way to tell from inside whether it failed
 * to open a device or opened one and played silence.  This asks the library
 * directly, outside the engine.
 *
 * install/lib/lib1/libopenal.so.1 is openal-soft-1.12.854 with alsa, oss and
 * wave backends only -- no PulseAudio backend exists in it, so everything has
 * to go through ALSA's pcm_pulse/pcm_pipewire plugin.
 *
 * ponytail: prototypes declared inline.  Pulling in AL/al.h means a 32-bit
 * -dev package for a library we already have the ABI of, and it is four
 * functions.
 *
 *   gcc -m32 -o analysis/tools/altest analysis/tools/altest.c \
 *       -Linstall/lib/lib1 -lopenal -Wl,-rpath,'$ORIGIN/../../install/lib/lib1'
 *   ALSOFT_CONF=... ./analysis/tools/altest [device]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void ALCdevice, ALCcontext;
extern ALCdevice  *alcOpenDevice(const char *);
extern ALCcontext *alcCreateContext(ALCdevice *, const int *);
extern int         alcMakeContextCurrent(ALCcontext *);
extern int         alcGetError(ALCdevice *);
extern const char *alcGetString(ALCdevice *, int);
extern const char *alGetString(int);

#define ALC_DEFAULT_DEVICE_SPECIFIER 0x1004
#define ALC_DEVICE_SPECIFIER         0x1005
#define ALC_ALL_DEVICES_SPECIFIER    0x1013
#define AL_VERSION                   0xB002
#define AL_RENDERER                  0xB003

/* ALC_*_SPECIFIER with a NULL device returns a \0\0-terminated list. */
static void dump_list(int token, const char *label) {
    const char *p = alcGetString(NULL, token);
    if (!p) { printf("  %s: (null)\n", label); return; }
    printf("  %s:\n", label);
    for (; *p; p += strlen(p) + 1) printf("    \"%s\"\n", p);
}

int main(int argc, char **argv) {
    const char *want = argc > 1 ? argv[1] : NULL;
    /* The 32-bit pipewire ALSA plugin segfaults inside alsa_close_playback at
     * exit (see REPORT), which eats a buffered stdout.  `stdbuf` cannot help:
     * its libstdbuf.so is 64-bit only. */
    setbuf(stdout, NULL);

    printf("enumeration:\n");
    dump_list(ALC_DEVICE_SPECIFIER, "ALC_DEVICE_SPECIFIER");
    dump_list(ALC_ALL_DEVICES_SPECIFIER, "ALC_ALL_DEVICES_SPECIFIER");
    printf("  default: \"%s\"\n", alcGetString(NULL, ALC_DEFAULT_DEVICE_SPECIFIER));

    printf("open(%s):\n", want ? want : "NULL/default");
    ALCdevice *dev = alcOpenDevice(want);
    if (!dev) { printf("  FAILED alcOpenDevice, alcGetError=0x%x\n", alcGetError(NULL)); return 1; }
    printf("  device opened, name=\"%s\"\n", alcGetString(dev, ALC_DEVICE_SPECIFIER));

    ALCcontext *ctx = alcCreateContext(dev, NULL);
    if (!ctx) { printf("  FAILED alcCreateContext, alcGetError=0x%x\n", alcGetError(dev)); return 1; }
    if (!alcMakeContextCurrent(ctx)) { printf("  FAILED alcMakeContextCurrent\n"); return 1; }

    printf("  AL_VERSION  = %s\n", alGetString(AL_VERSION));
    printf("  AL_RENDERER = %s\n", alGetString(AL_RENDERER));
    printf("OK\n");
    return 0;
}
