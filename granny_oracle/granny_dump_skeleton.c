/* Stage 4: unblock grn2gr2.dll's converter (05-03 Task 2), then dump
 * per-bone skeleton facts from a successfully converted file and run the
 * D-09 blocking counterfactual against a pre-computed reference.
 *
 * Clean-room posture unchanged from granny_probe.c / granny_dump_geometry.c:
 * calls exported functions, reads their output. Struct field offsets below
 * (Name@0, ParentIndex@4, LocalTransform@8, Position@12 within it) come from
 * the official public RAD Granny SDK 2.11.8.0 header
 * (Granny_Common_2_11_8_0_Release/include/granny.h) -- used strictly as
 * documentation of a struct layout, per D-21/D-23. No SDK source or comment
 * text is reproduced; only the field offsets, which are facts.
 *
 * Command line selects ONE action per process (a crash inside grn2gr2.dll
 * takes the whole process down, so hypotheses cannot share a run):
 *
 *   conv   <p1> <p2> <bool> <p4>
 *       Calls GRN2GR2ConvertGRNFile(p1, p2, bool, p4) once, then tries to
 *       load p4 (the leading char* the docs list last) via granny2.dll to
 *       see whether a real file resulted. Used for every H1 combo.
 *
 *   dump   <gr2path> <refpath>
 *       Loads gr2path via granny2.dll, walks its one skeleton's bones
 *       (Name/ParentIndex/local Position+Orientation), composes each bone's
 *       WORLD position by the same parent-chain recursion verify_ref.py
 *       uses, and prints one `skelbone` fact line per bone. Then reads
 *       refpath -- a flat `name<TAB>x<TAB>y<TAB>z` reference file already
 *       produced by verify_ref.py's bone_facts() + grn_bonenames.py's
 *       documented-arm resolution (both reused unmodified, never
 *       reimplemented here) -- joins ORACLE bone name to REFERENCE world
 *       position (name join, per name_join_required=yes, findings row 591),
 *       and prints the D-09 fix-arm max distance. Also dumps mesh vertex
 *       counts per mesh, for D-15.
 *
 *   control <gr2path> <refpath> <bonename> <dx> <dy> <dz>
 *       Same as dump, but perturbs the named oracle bone's LOCAL position by
 *       (dx,dy,dz) before composing world space -- the D-09 control arm,
 *       which must disagree more than the fix arm agreed.
 */
#define WINAPI __stdcall
typedef unsigned int u32;
typedef void* HMOD;

extern HMOD  WINAPI LoadLibraryA(const char*);
extern void* WINAPI GetProcAddress(HMOD, const char*);
extern u32   WINAPI GetLastError(void);
extern void  WINAPI ExitProcess(u32);
extern void* WINAPI GetStdHandle(u32);
extern int   WINAPI WriteFile(void*, const void*, u32, u32*, void*);
extern char* WINAPI GetCommandLineA(void);
extern void* WINAPI CreateFileA(const char*, u32, u32, void*, u32, u32, void*);
extern int   WINAPI ReadFile(void*, void*, u32, u32*, void*);
extern u32   WINAPI GetFileSize(void*, u32*);
extern int   WINAPI CloseHandle(void*);
extern void* WINAPI VirtualAlloc(void*, u32, u32, u32);

int _fltused = 0x9875;

/* ---- tiny freestanding stdio ---- */
static void* hout;
static u32 slen(const char* s) { u32 n = 0; while (s && s[n] && n < 8192) n++; return n; }
static void S(const char* s) { u32 w; if (s) WriteFile(hout, s, slen(s), &w, 0); }
static void C(char c) { u32 w; WriteFile(hout, &c, 1, &w, 0); }
static void HEX(u32 v) { const char* d = "0123456789abcdef"; char b[8];
    for (int i = 0; i < 8; i++) { b[7 - i] = d[v & 0xf]; v >>= 4; } u32 w; WriteFile(hout, b, 8, &w, 0); }
static void DEC(int v) { char b[16]; int i = 0; u32 u2; if (v < 0) { C('-'); u2 = (u32)(-v); } else u2 = (u32)v;
    if (!u2) { C('0'); return; } while (u2) { b[i++] = '0' + (char)(u2 % 10); u2 /= 10; } while (i--) C(b[i]); }
static void NL(void) { C('\n'); }
static void FLT(float f) {
    if (f < 0) { C('-'); f = -f; }
    u32 ip = (u32)f; DEC((int)ip); C('.');
    float frac = f - (float)ip; if (frac < 0) frac = 0;
    u32 fr = (u32)(frac * 1000000.0f + 0.5f);
    u32 div = 100000; while (div > 1 && fr < div) { C('0'); div /= 10; }
    DEC((int)fr);
}
static int seq(const char* a, const char* b) { u32 i = 0; while (a[i] && b[i]) { if (a[i] != b[i]) return 0; i++; } return a[i] == b[i]; }
static int scaselessq(const char* a, const char* b) {
    u32 i = 0;
    for (;; i++) {
        char ca = a[i], cb = b[i];
        if (ca >= 'A' && ca <= 'Z') ca = (char)(ca - 'A' + 'a');
        if (cb >= 'A' && cb <= 'Z') cb = (char)(cb - 'A' + 'a');
        if (ca != cb) return 0;
        if (!ca) return 1;
    }
}
static float fabsf_(float f) { return f < 0 ? -f : f; }
static float sqrtf_(float x) {
    if (x <= 0) return 0;
    float g = x;
    for (int i = 0; i < 24; i++) g = 0.5f * (g + x / g);
    return g;
}

/* Split GetCommandLineA() into whitespace-separated tokens, quotes respected.
 * argv[0] is the exe name (skipped by the caller). */
#define MAXTOK 8
static char* g_tok[MAXTOK];
static int g_ntok;
static void tokenize(void) {
    static char buf[2048];
    char* c = GetCommandLineA();
    int bi = 0, inq = 0;
    g_ntok = 0;
    char* cur = 0;
    for (; *c && g_ntok < MAXTOK; c++) {
        if (*c == '"') { inq = !inq; continue; }
        if (!inq && (*c == ' ' || *c == '\t')) {
            if (cur) { buf[bi++] = 0; g_tok[g_ntok++] = cur; cur = 0; }
            continue;
        }
        if (!cur) cur = buf + bi;
        buf[bi++] = *c;
    }
    if (cur && g_ntok < MAXTOK) { buf[bi++] = 0; g_tok[g_ntok++] = cur; }
    /* g_tok[0] is argv[0] (the exe path) per GetCommandLineA() convention --
     * drop it so every subcommand's g_tok[0].. indexing is the mode/args a
     * caller actually typed, not off-by-one against the exe path. */
    if (g_ntok > 0) {
        for (int i = 1; i < g_ntok; i++) g_tok[i - 1] = g_tok[i];
        g_ntok--;
    }
}

typedef void  (WINAPI *PCONV)(const char*, const char*, int, const char*);
typedef const char* (WINAPI *PVER)(void);
typedef void* (WINAPI *PREAD)(const char*);
typedef void* (WINAPI *PINFO)(void*);
typedef int   (WINAPI *PI_P)(void*);
typedef void* (WINAPI *PP_P)(void*);
typedef void  (WINAPI *PSETLOG)(void*);

static void __cdecl logfn(int t, int o, const char* m, u32 a, u32 b, void* u) {
    (void)o; (void)a; (void)b; (void)u; S("  [log t="); DEC(t); S("] "); S(m); NL();
}
static struct { void* fn; void* ud; } logcb;

/* ---- documented granny_bone layout (32-bit), header-fact only ---- */
#define BONE_STRIDE   152
#define OFF_NAME      0
#define OFF_PARENT    4
#define OFF_POS       12   /* LocalTransform(8) + Position(4) */
#define OFF_QUAT      24   /* Position(12) follows Position(4) -> 12+12=24 */

#define MAX_BONES 256
static const char* g_name[MAX_BONES];
static int   g_parent[MAX_BONES];
static float g_lpos[MAX_BONES][3];
static float g_lquat[MAX_BONES][4]; /* x y z w */
static float g_wpos[MAX_BONES][3];
static int   g_ok[MAX_BONES];

static void quat_rotate(const float q[4], const float v[3], float out[3]) {
    float qx = q[0], qy = q[1], qz = q[2], qw = q[3];
    float r00 = 1 - 2 * (qy * qy + qz * qz), r01 = 2 * (qx * qy - qz * qw), r02 = 2 * (qx * qz + qy * qw);
    float r10 = 2 * (qx * qy + qz * qw), r11 = 1 - 2 * (qx * qx + qz * qz), r12 = 2 * (qy * qz - qx * qw);
    float r20 = 2 * (qx * qz - qy * qw), r21 = 2 * (qy * qz + qx * qw), r22 = 1 - 2 * (qx * qx + qy * qy);
    out[0] = r00 * v[0] + r01 * v[1] + r02 * v[2];
    out[1] = r10 * v[0] + r11 * v[1] + r12 * v[2];
    out[2] = r20 * v[0] + r21 * v[1] + r22 * v[2];
}

/* World position of bone i = parent's world position + parent's world
 * rotation applied to bone i's local position. Rotation itself is not
 * accumulated (translations only are compared, per the plan's scope) -- a
 * rigid game skeleton's ScaleShear is expected identity and is not read. */
static void compose_world(int n) {
    static int done[MAX_BONES];
    for (int i = 0; i < n; i++) done[i] = 0;
    int progress = 1, left = n;
    while (progress && left > 0) {
        progress = 0;
        for (int i = 0; i < n; i++) {
            if (done[i] || !g_ok[i]) continue;
            int p = g_parent[i];
            if (p < 0 || p >= n) {
                g_wpos[i][0] = g_lpos[i][0]; g_wpos[i][1] = g_lpos[i][1]; g_wpos[i][2] = g_lpos[i][2];
                done[i] = 1; progress = 1; left--; continue;
            }
            if (!done[p]) continue;
            float rotated[3];
            /* approximate: apply parent's own local orientation only (chain
             * built incrementally bone-by-bone during this same pass is not
             * attempted -- see the README note on this simplification). */
            quat_rotate(g_lquat[p], g_lpos[i], rotated);
            g_wpos[i][0] = g_wpos[p][0] + rotated[0];
            g_wpos[i][1] = g_wpos[p][1] + rotated[1];
            g_wpos[i][2] = g_wpos[p][2] + rotated[2];
            done[i] = 1; progress = 1; left--;
        }
    }
}

static HMOD load_granny2(void) {
    HMOD g = LoadLibraryA("granny2.dll");
    if (!g) { S("no granny2\n"); ExitProcess(1); }
    return g;
}

static void cmd_conv(void) {
    if (g_ntok < 5) { S("conv needs 4 args: p1 p2 bool p4\n"); ExitProcess(2); }
    const char* p1 = g_tok[1]; const char* p2 = g_tok[2];
    int bflag = (g_tok[3][0] == '1'); const char* p4 = g_tok[4];

    HMOD c = LoadLibraryA("grn2gr2.dll");
    if (!c) { S("no grn2gr2\n"); ExitProcess(1); }
    PCONV Conv = (PCONV)GetProcAddress(c, "?GRN2GR2ConvertGRNFile@@YGXPBD0_N0@Z");
    if (!Conv) { S("no Conv export\n"); ExitProcess(1); }

    S("conv\tp1="); S(p1); S("\tp2="); S(p2); S("\tbool="); DEC(bflag); S("\tp4="); S(p4); NL();

    /* Output-file hygiene (Rule 2 fix, 05-03 Task 2): a prior scratch probe
     * (gh9.c, not part of this plan) read a STALE .gr2 left over from an
     * earlier run after Conv() silently no-op'd on bad input, and reported a
     * false "success" -- md5-identical to a file a day older. Truncate any
     * existing p4 to 0 bytes before calling Conv(), using only CreateFileA
     * (already in kernel32.def, not adding DeleteFileA/GetFileAttributesA to
     * a .def file this plan doesn't own), so a silent no-op leaves an empty
     * file, not stale content, for GrannyReadEntireFile to accidentally pick
     * up. */
    {
        void* th = CreateFileA(p4, 0x40000000u /*GENERIC_WRITE*/, 0, 0,
                                2 /*CREATE_ALWAYS*/, 0x80, 0);
        if (th == (void*)-1) {
            S("result\tHARNESS_ERROR could not truncate p4 before convert\n");
            ExitProcess(3);
        }
        CloseHandle(th);
    }

    S("calling...\n");
    Conv(p1, p2, bflag, p4);
    S("returned\n");

    {
        void* oh = CreateFileA(p4, 0x80000000u /*GENERIC_READ*/, 1, 0,
                                3 /*OPEN_EXISTING*/, 0x80, 0);
        u32 wrote = 0;
        if (oh != (void*)-1) { wrote = GetFileSize(oh, 0); CloseHandle(oh); }
        if (wrote == 0) {
            S("result\tNO_VALID_OUTPUT reason=convert_did_not_write_p4\n");
            ExitProcess(1);
        }
    }

    HMOD g = load_granny2();
    PREAD Read = (PREAD)GetProcAddress(g, "_GrannyReadEntireFile@4");
    PINFO Info = (PINFO)GetProcAddress(g, "_GrannyGetFileInfo@4");
    void* f = Read(p4);
    if (!f) { S("result\tNO_VALID_OUTPUT reason=granny2_could_not_read p4\n"); ExitProcess(1); }
    void* fi = Info(f);
    if (!fi) { S("result\tNO_VALID_OUTPUT reason=no_file_info\n"); ExitProcess(1); }
    S("result\tCONVERTED out="); S(p4); NL();
    ExitProcess(0);
}

/* Locate the skeleton via the same dword-offset-guessing style
 * granny_dump_geometry.c already established for MeshCount/Meshes
 * ([13]/[14]); SkeletonCount/Skeletons are read the same way and printed
 * raw first so the guess is auditable, not asserted blind. */
static void dump_skeleton_and_meshes(void* fi, HMOD g, const char* refpath) {
    u32* w = (u32*)fi;
    S("\n-- file_info dwords 0..17 --\n");
    for (int i = 0; i < 18; i++) { S(" ["); DEC(i); S("] 0x"); HEX(w[i]); NL(); }

    PI_P VCount = (PI_P)GetProcAddress(g, "_GrannyGetMeshVertexCount@4");
    PI_P TCount = (PI_P)GetProcAddress(g, "_GrannyGetMeshTriangleCount@4");
    /* file_info layout below is NOT a fresh guess: SkeletonCount@[7]/
     * Skeletons@[8] and MeshCount@[13]/Meshes@[14] were established by a
     * prior scratch probe (gh9.c) that printed raw dwords and matched them
     * against sane values (BoneCount=68 root name "__Root" for entry 589's
     * mesh, BoneCount=101 for entry 2845's motion) -- reused here, not
     * reguessed. That probe's *conversion* result was later found to be a
     * stale-file artifact (see the truncate-before-convert hygiene fix
     * above); its
     * *offset layout*, read from a `.gr2` that unquestionably existed on
     * disk at read time, is independent of that and still trustworthy. */
    u32 meshCount = w[13];
    u32** meshes = (u32**)w[14];

    u32 skelCount = w[7];
    u32** skels = (u32**)w[8];
    S("\n-- skeletons (count="); DEC((int)skelCount); S(") --\n");
    if (skelCount == 0 || skelCount > 4 || !skels) {
        S("skel\tNO_SKELETON_AT_GUESSED_OFFSET\n");
        return;
    }
    u32* skel = skels[0];
    const char* skelName = (const char*)skel[0];
    int boneCount = (int)skel[1];
    u32* bones = (u32*)skel[2];
    S("skel\tname="); S(skelName); S("\tBoneCount="); DEC(boneCount); NL();
    if (boneCount <= 0 || boneCount > MAX_BONES || !bones) {
        S("skel\tBONE_ARRAY_UNREADABLE\n");
        return;
    }

    /* granny_bone stride is 152B (documented, header-fact) -- walk the raw
     * array by that stride rather than trusting a pointer array. */
    char* base = (char*)bones;
    int acyclic = 1;
    for (int i = 0; i < boneCount; i++) {
        char* b = base + (u32)i * BONE_STRIDE;
        const char* nm = *(const char**)(b + OFF_NAME);
        int parent = *(int*)(b + OFF_PARENT);
        float* pos = (float*)(b + OFF_POS);
        float* quat = (float*)(b + OFF_QUAT);
        g_name[i] = nm; g_parent[i] = parent;
        g_lpos[i][0] = pos[0]; g_lpos[i][1] = pos[1]; g_lpos[i][2] = pos[2];
        g_lquat[i][0] = quat[0]; g_lquat[i][1] = quat[1]; g_lquat[i][2] = quat[2]; g_lquat[i][3] = quat[3];
        g_ok[i] = 1;
    }
    /* Acyclic check on ParentIndex, per the plan's requirement -- ASCII
     * printability of Name is explicitly NOT accepted as evidence (A1). */
    for (int i = 0; i < boneCount; i++) {
        int seen[MAX_BONES]; for (int k = 0; k < boneCount; k++) seen[k] = 0;
        int cur = i, steps = 0;
        while (cur >= 0 && cur < boneCount) {
            if (seen[cur]) { acyclic = 0; break; }
            seen[cur] = 1;
            cur = g_parent[cur];
            if (++steps > boneCount) { acyclic = 0; break; }
        }
    }
    S("skel\tacyclic="); S(acyclic ? "true" : "false"); NL();

    S("\n-- meshes (count="); DEC((int)meshCount); S(") --\n");
    if (meshCount > 0 && meshCount < 64 && meshes) {
        for (u32 m = 0; m < meshCount; m++) {
            void* mesh = meshes[m];
            S(" mesh\tindex="); DEC((int)m);
            S("\tname="); S((const char*)((u32*)mesh)[0]);
            S("\tvertices="); DEC(VCount ? (int)VCount(mesh) : -1);
            S("\ttriangles="); DEC(TCount ? (int)TCount(mesh) : -1); NL();
        }
    }

    compose_world(boneCount);
    for (int i = 0; i < boneCount; i++) {
        S("skelbone\tindex="); DEC(i); S("\tname="); S(g_name[i] ? g_name[i] : "(null)");
        S("\tparent="); DEC(g_parent[i]);
        S("\tworldpos="); FLT(g_wpos[i][0]); C(','); FLT(g_wpos[i][1]); C(','); FLT(g_wpos[i][2]); NL();
    }

    /* Join by NAME against the reference file (name_join_required=yes,
     * row 591) and report the fix-arm max distance. */
    void* h = CreateFileA(refpath, 0x80000000u, 1, 0, 3, 0x80, 0);
    if (h == (void*)-1) { S("oracle\tarm=fix\tERROR cannot open refpath\n"); return; }
    u32 sz = GetFileSize(h, 0);
    char* rbuf = (char*)VirtualAlloc(0, sz + 1, 0x3000, 4);
    u32 got = 0; ReadFile(h, rbuf, sz, &got, 0); CloseHandle(h);
    rbuf[got] = 0;

    float maxd = -1; int joined = 0, unjoined = boneCount;
    char* p = rbuf;
    while (p < rbuf + got) {
        char* line = p;
        while (p < rbuf + got && *p != '\n') p++;
        if (p > rbuf + got) break;
        *p = 0; p++;
        /* line: name\tx\ty\tz */
        char* t1 = line; while (*t1 && *t1 != '\t') t1++;
        if (!*t1) continue;
        *t1 = 0; char* xs = t1 + 1;
        char* t2 = xs; while (*t2 && *t2 != '\t') t2++;
        if (!*t2) continue; *t2 = 0; char* ys = t2 + 1;
        char* t3 = ys; while (*t3 && *t3 != '\t') t3++;
        if (!*t3) continue; *t3 = 0; char* zs = t3 + 1;
        /* tiny float parser, decimal only (reference file is our own
         * output, always plain decimal) */
        float rx = 0, ry = 0, rz = 0;
        float* targets[3] = { &rx, &ry, &rz };
        char* srcs[3] = { xs, ys, zs };
        for (int k = 0; k < 3; k++) {
            char* s = srcs[k]; int neg = 0; if (*s == '-') { neg = 1; s++; }
            float v = 0; while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
            if (*s == '.') { s++; float scale = 0.1f; while (*s >= '0' && *s <= '9') { v += (*s - '0') * scale; scale *= 0.1f; s++; } }
            *targets[k] = neg ? -v : v;
        }
        for (int i = 0; i < boneCount; i++) {
            if (!g_name[i] || !scaselessq(g_name[i], line)) continue;
            float dx = g_wpos[i][0] - rx, dy = g_wpos[i][1] - ry, dz = g_wpos[i][2] - rz;
            float d = sqrtf_(dx * dx + dy * dy + dz * dz);
            if (d > maxd) maxd = d;
            joined++; unjoined--;
            break;
        }
    }
    S("oracle\tjoined="); DEC(joined); S("\tunjoined="); DEC(unjoined); NL();
    if (joined == 0) { S("oracle\tarm=fix\tmaxdist=n/a\tverdict=UNJOINED\n"); return; }
    S("oracle\tarm=fix\tmaxdist="); FLT(maxd); S("\tverdict="); S(maxd < 0.01f ? "PASS" : "FAIL"); NL();
}

static void cmd_dump(void) {
    if (g_ntok < 3) { S("dump needs 2 args: gr2path refpath\n"); ExitProcess(2); }
    const char* gr2 = g_tok[1]; const char* refpath = g_tok[2];
    HMOD g = load_granny2();
    PVER Ver = (PVER)GetProcAddress(g, "_GrannyGetVersionString@0");
    PREAD Read = (PREAD)GetProcAddress(g, "_GrannyReadEntireFile@4");
    PINFO Info = (PINFO)GetProcAddress(g, "_GrannyGetFileInfo@4");
    PSETLOG SetLg = (PSETLOG)GetProcAddress(g, "_GrannySetLogCallback@4");
    S("granny "); S(Ver()); NL();
    if (SetLg) { logcb.fn = (void*)logfn; SetLg(&logcb); }
    void* f = Read(gr2);
    if (!f) { S("FAIL read gr2\n"); ExitProcess(1); }
    void* fi = Info(f);
    if (!fi) { S("FAIL info\n"); ExitProcess(1); }
    dump_skeleton_and_meshes(fi, g, refpath);
    S("done\n");
    ExitProcess(0);
}

static void cmd_control(void) {
    if (g_ntok < 7) { S("control needs 6 args: gr2path refpath bonename dx dy dz\n"); ExitProcess(2); }
    const char* gr2 = g_tok[1]; const char* refpath = g_tok[2]; const char* bonename = g_tok[3];
    float d[3];
    for (int k = 0; k < 3; k++) {
        char* s = g_tok[4 + k]; int neg = 0; if (*s == '-') { neg = 1; s++; }
        float v = 0; while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
        if (*s == '.') { s++; float sc = 0.1f; while (*s >= '0' && *s <= '9') { v += (*s - '0') * sc; sc *= 0.1f; s++; } }
        d[k] = neg ? -v : v;
    }
    HMOD g = load_granny2();
    PREAD Read = (PREAD)GetProcAddress(g, "_GrannyReadEntireFile@4");
    PINFO Info = (PINFO)GetProcAddress(g, "_GrannyGetFileInfo@4");
    void* f = Read(gr2);
    if (!f) { S("FAIL read gr2\n"); ExitProcess(1); }
    void* fi = Info(f);
    if (!fi) { S("FAIL info\n"); ExitProcess(1); }
    u32* w = (u32*)fi;
    u32 skelCount = w[15]; u32** skels = (u32**)w[16];
    if (skelCount == 0 || skelCount > 4 || !skels) { S("skel\tNO_SKELETON\n"); ExitProcess(1); }
    u32* skel = skels[0];
    int boneCount = (int)skel[1];
    u32* bones = (u32*)skel[2];
    if (boneCount <= 0 || boneCount > MAX_BONES) { S("skel\tBAD_BONE_COUNT\n"); ExitProcess(1); }
    char* base = (char*)bones;
    int target = -1;
    for (int i = 0; i < boneCount; i++) {
        char* b = base + (u32)i * BONE_STRIDE;
        const char* nm = *(const char**)(b + OFF_NAME);
        int parent = *(int*)(b + OFF_PARENT);
        float* pos = (float*)(b + OFF_POS);
        float* quat = (float*)(b + OFF_QUAT);
        g_name[i] = nm; g_parent[i] = parent;
        g_lpos[i][0] = pos[0]; g_lpos[i][1] = pos[1]; g_lpos[i][2] = pos[2];
        g_lquat[i][0] = quat[0]; g_lquat[i][1] = quat[1]; g_lquat[i][2] = quat[2]; g_lquat[i][3] = quat[3];
        g_ok[i] = 1;
        if (nm && scaselessq(nm, bonename)) target = i;
    }
    if (target < 0) { S("oracle\tarm=control\tERROR bone not found\n"); ExitProcess(1); }
    S("control\tperturbing bone="); S(bonename); S("\tby="); FLT(d[0]); C(','); FLT(d[1]); C(','); FLT(d[2]); NL();
    g_lpos[target][0] += d[0]; g_lpos[target][1] += d[1]; g_lpos[target][2] += d[2];
    compose_world(boneCount);

    void* h = CreateFileA(refpath, 0x80000000u, 1, 0, 3, 0x80, 0);
    if (h == (void*)-1) { S("oracle\tarm=control\tERROR cannot open refpath\n"); ExitProcess(1); }
    u32 sz = GetFileSize(h, 0);
    char* rbuf = (char*)VirtualAlloc(0, sz + 1, 0x3000, 4);
    u32 got = 0; ReadFile(h, rbuf, sz, &got, 0); CloseHandle(h);
    rbuf[got] = 0;
    float maxd = -1; int joined = 0;
    char* p = rbuf;
    while (p < rbuf + got) {
        char* line = p;
        while (p < rbuf + got && *p != '\n') p++;
        if (p > rbuf + got) break;
        *p = 0; p++;
        char* t1 = line; while (*t1 && *t1 != '\t') t1++;
        if (!*t1) continue; *t1 = 0; char* xs = t1 + 1;
        char* t2 = xs; while (*t2 && *t2 != '\t') t2++;
        if (!*t2) continue; *t2 = 0; char* ys = t2 + 1;
        char* t3 = ys; while (*t3 && *t3 != '\t') t3++;
        if (!*t3) continue; *t3 = 0; char* zs = t3 + 1;
        float rx = 0, ry = 0, rz = 0; float* tg[3] = { &rx, &ry, &rz }; char* sr[3] = { xs, ys, zs };
        for (int k = 0; k < 3; k++) {
            char* s = sr[k]; int neg = 0; if (*s == '-') { neg = 1; s++; }
            float v = 0; while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
            if (*s == '.') { s++; float sc = 0.1f; while (*s >= '0' && *s <= '9') { v += (*s - '0') * sc; sc *= 0.1f; s++; } }
            *tg[k] = neg ? -v : v;
        }
        for (int i = 0; i < boneCount; i++) {
            if (!g_name[i] || !scaselessq(g_name[i], line)) continue;
            float dx = g_wpos[i][0] - rx, dy = g_wpos[i][1] - ry, dz = g_wpos[i][2] - rz;
            float dd = sqrtf_(dx * dx + dy * dy + dz * dz);
            if (dd > maxd) maxd = dd;
            joined++;
            break;
        }
    }
    if (joined == 0) { S("oracle\tarm=control\tmaxdist=n/a\tverdict=UNJOINED\n"); ExitProcess(1); }
    S("oracle\tarm=control\tmaxdist="); FLT(maxd); S("\tverdict="); S(maxd < 0.01f ? "PASS" : "FAIL"); NL();
    ExitProcess(0);
}

void mainCRTStartup(void) {
    hout = GetStdHandle((u32)-11);
    tokenize();
    if (g_ntok < 1) { S("usage: conv|dump|control ...\n"); ExitProcess(2); }
    if (seq(g_tok[0], "conv")) cmd_conv();
    else if (seq(g_tok[0], "dump")) cmd_dump();
    else if (seq(g_tok[0], "control")) cmd_control();
    else { S("unknown mode\n"); ExitProcess(2); }
    ExitProcess(0);
}
