/* granny2.dll oracle harness -- freestanding 32-bit PE, no CRT.
 *
 * Observes OUTPUTS of granny2.dll's exported API only. No decompilation,
 * no disassembly, nothing derived from RAD's SDK source.
 *
 * v2: installs a log callback so the library reports WHY it rejects a file,
 *     and tries both the path reader and the memory reader.
 */

#define WINAPI __stdcall
typedef unsigned int  u32;
typedef void*         HMOD;

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

static void* hout;
static u32 slen(const char* s){ u32 n=0; while(s && s[n] && n<4096) n++; return n; }
static void S(const char* s){ u32 w; if(s) WriteFile(hout,s,slen(s),&w,0); }
static void C(char c){ u32 w; WriteFile(hout,&c,1,&w,0); }
static void HEX(u32 v){ const char* d="0123456789abcdef"; char b[8];
    for(int i=0;i<8;i++){ b[7-i]=d[v&0xf]; v>>=4; } u32 w; WriteFile(hout,b,8,&w,0); }
static void DEC(u32 v){ char b[12]; int i=0; if(!v){C('0');return;}
    while(v){ b[i++]='0'+(v%10); v/=10; } while(i--) C(b[i]); }
static void NL(void){ C('\n'); }

typedef const char* (WINAPI *PVER)(void);
typedef void* (WINAPI *PREAD)(const char*);
typedef void* (WINAPI *PREADMEM)(u32, void*);
typedef void* (WINAPI *PINFO)(void*);
typedef void  (WINAPI *PSETLOG)(void*);
typedef int   (WINAPI *PISGRANNY)(u32, void*, void*);

/* granny_log_callback = { function ptr, user data }.  The log function is
   __cdecl in the SDK, so extra trailing args are harmless to us. */
static void __cdecl logfn(int type, int origin, const char* a3, u32 a4, u32 a5, void* ud)
{
    (void)ud;
    S("  [granny log] type="); DEC((u32)type);
    S(" origin="); DEC((u32)origin);
    S("\n     a3=\""); S(a3); S("\"\n");
    S("     a4=0x"); HEX(a4); S("  a5=0x"); HEX(a5); NL();
}
static struct { void* fn; void* ud; } logcb;

static HMOD g;
static void* sym(const char* n){ void* p=GetProcAddress(g,n);
    if(!p){ S("!! missing export "); S(n); NL(); } return p; }

static const char* argfile(void){
    char* c = GetCommandLineA(); char* last=0; int inq=0;
    for(char* p=c; *p; p++){
        if(*p=='"'){ inq=!inq; continue; }
        if(!inq && (*p==' '||*p=='\t')){
            while(p[1]==' '||p[1]=='\t') p++;
            if(p[1]) last=p+1;
        }
    }
    return last?last:"GLADIATOR.GRN";
}

void mainCRTStartup(void){
    hout = GetStdHandle((u32)-11);
    g = LoadLibraryA("granny2.dll");
    if(!g){ S("FAIL LoadLibrary err="); DEC(GetLastError()); NL(); ExitProcess(1); }

    PVER      Ver   = (PVER)     sym("_GrannyGetVersionString@0");
    PREAD     Read  = (PREAD)    sym("_GrannyReadEntireFile@4");
    PREADMEM  ReadM = (PREADMEM) sym("_GrannyReadEntireFileFromMemory@8");
    PINFO     Info  = (PINFO)    sym("_GrannyGetFileInfo@4");
    PSETLOG   SetLg = (PSETLOG)  sym("_GrannySetLogCallback@4");
    PISGRANNY IsGr  = (PISGRANNY)sym("_GrannyIsGrannyFile@12");

    S("version\t"); S(Ver()); NL();

    if(SetLg){ logcb.fn=(void*)logfn; logcb.ud=0; SetLg(&logcb); S("log callback installed\n"); }

    const char* fn = argfile();
    S("file\t"); S(fn); NL();

    /* --- attempt 1: path reader --- */
    S("\n== GrannyReadEntireFile ==\n");
    void* f = Read(fn);
    S("result\t0x"); HEX((u32)f); NL();

    /* --- attempt 2: slurp to memory, then memory reader --- */
    if(!f && ReadM){
        void* h = CreateFileA(fn, 0x80000000u, 1, 0, 3, 0x80, 0);
        if(h != (void*)-1){
            u32 sz = GetFileSize(h,0);
            void* buf = VirtualAlloc(0, sz+16, 0x3000, 4);
            u32 got=0; ReadFile(h, buf, sz, &got, 0); CloseHandle(h);
            S("\n== slurped "); DEC(got); S(" bytes ==\n");
            if(IsGr){ S("IsGrannyFile -> "); DEC((u32)IsGr(got, buf, 0)); NL(); }
            S("== GrannyReadEntireFileFromMemory ==\n");
            f = ReadM(got, buf);
            S("result\t0x"); HEX((u32)f); NL();
        } else S("could not open file for slurp\n");
    }

    if(!f){ S("FAIL: granny refused the file\n"); ExitProcess(1); }

    void* fi = Info(f);
    S("GetFileInfo\t0x"); HEX((u32)fi); NL();
    if(!fi){ S("FAIL: no file info\n"); ExitProcess(1); }

    S("\n-- granny_file_info raw dump --\n");
    u32* w = (u32*)fi;
    for(int i=0;i<48;i++){
        u32 v=w[i];
        S("  ["); if(i<10) C(' '); DEC((u32)i); S("] 0x"); HEX(v); S("  "); DEC(v); S("  ");
        S(v==0?"zero":(v<8192?"COUNT?":"ptr?")); NL();
    }
    S("done\n");
    ExitProcess(0);
}
