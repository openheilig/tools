/* Stage 3: GRN -> GR2 (grn2gr2.dll) -> granny2.dll -> ground-truth geometry.
 * Vertex layout is identified by POINTER-COMPARING GrannyGetMeshVertexType()
 * against the exported Granny*VertexType symbols -- exact, not inferred.
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

int _fltused = 0x9875;
static void* hout;
static u32 slen(const char* s){ u32 n=0; while(s&&s[n]&&n<8192) n++; return n; }
static void S(const char* s){ u32 w; if(s) WriteFile(hout,s,slen(s),&w,0); }
static void C(char c){ u32 w; WriteFile(hout,&c,1,&w,0); }
static void HEX(u32 v){ const char* d="0123456789abcdef"; char b[8];
    for(int i=0;i<8;i++){ b[7-i]=d[v&0xf]; v>>=4; } u32 w; WriteFile(hout,b,8,&w,0); }
static void DEC(u32 v){ char b[12]; int i=0; if(!v){C('0');return;}
    while(v){ b[i++]='0'+(v%10); v/=10; } while(i--) C(b[i]); }
static void NL(void){ C('\n'); }
/* print a float with 3 decimals */
static void FLT(float f){
    if(f<0){ C('-'); f=-f; }
    u32 ip=(u32)f; DEC(ip); C('.');
    u32 fr=(u32)((f-(float)ip)*1000.0f+0.5f);
    if(fr<100) C('0'); if(fr<10) C('0'); DEC(fr);
}

typedef void (WINAPI *PCONV)(const char*,const char*,int,const char*);
typedef const char* (WINAPI *PVER)(void);
typedef void* (WINAPI *PREAD)(const char*);
typedef void* (WINAPI *PINFO)(void*);
typedef int   (WINAPI *PI_P)(void*);
typedef void* (WINAPI *PP_P)(void*);
typedef void  (WINAPI *PSETLOG)(void*);

static void __cdecl logfn(int t,int o,const char* m,u32 a,u32 b,void* u){
    (void)o;(void)a;(void)b;(void)u; S("  [log t="); DEC((u32)t); S("] "); S(m); NL(); }
static struct { void* fn; void* ud; } logcb;

static const char* VTNAMES[] = {
 "GrannyP3VertexType","GrannyPT32VertexType","GrannyPN33VertexType",
 "GrannyPNT332VertexType","GrannyPNT333VertexType","GrannyPNG333VertexType",
 "GrannyPNGT3332VertexType","GrannyPNGB3333VertexType","GrannyPNGBT33332VertexType",
 "GrannyPNGBT33333VertexType","GrannyGBX333VertexType",
 "GrannyPWN313VertexType","GrannyPWN323VertexType","GrannyPWN343VertexType",
 "GrannyPWNT3132VertexType","GrannyPWNT3232VertexType","GrannyPWNT3432VertexType",
 "GrannyPWNG3133VertexType","GrannyPWNG3233VertexType","GrannyPWNG3433VertexType",
 "GrannyPWNGB31333VertexType","GrannyPWNGB32333VertexType","GrannyPWNGB34333VertexType",
 "GrannyPWNGT31332VertexType","GrannyPWNGT32332VertexType","GrannyPWNGT34332VertexType",
 "GrannyPWNGBT313332VertexType","GrannyPWNGBT323332VertexType","GrannyPWNGBT343332VertexType",
 0 };

void mainCRTStartup(void){
    hout = GetStdHandle((u32)-11);

    HMOD c = LoadLibraryA("grn2gr2.dll");
    if(!c){ S("no grn2gr2\n"); ExitProcess(1); }
    PCONV Conv=(PCONV)GetProcAddress(c,"?GRN2GR2ConvertGRNFile@@YGXPBD0_N0@Z");
    S("converting...\n");
    Conv("GLADIATOR.GRN","out.gr2",0,"");
    S("converted\n");

    HMOD g = LoadLibraryA("granny2.dll");
    if(!g){ S("no granny2\n"); ExitProcess(1); }
    PVER Ver=(PVER)GetProcAddress(g,"_GrannyGetVersionString@0");
    PREAD Read=(PREAD)GetProcAddress(g,"_GrannyReadEntireFile@4");
    PINFO Info=(PINFO)GetProcAddress(g,"_GrannyGetFileInfo@4");
    PSETLOG SetLg=(PSETLOG)GetProcAddress(g,"_GrannySetLogCallback@4");
    PI_P VCount=(PI_P)GetProcAddress(g,"_GrannyGetMeshVertexCount@4");
    PP_P VType =(PP_P)GetProcAddress(g,"_GrannyGetMeshVertexType@4");
    PP_P VVerts=(PP_P)GetProcAddress(g,"_GrannyGetMeshVertices@4");
    PI_P ICount=(PI_P)GetProcAddress(g,"_GrannyGetMeshIndexCount@4");
    PI_P TCount=(PI_P)GetProcAddress(g,"_GrannyGetMeshTriangleCount@4");
    PI_P TotSz=(PI_P)GetProcAddress(g,"_GrannyGetTotalObjectSize@4");
    PI_P MemSz=(PI_P)GetProcAddress(g,"_GrannyGetMemberTypeSize@4");
    PI_P BPI  =(PI_P)GetProcAddress(g,"_GrannyGetMeshBytesPerIndex@4");

    S("granny "); S(Ver()); NL();
    if(SetLg){ logcb.fn=(void*)logfn; SetLg(&logcb); }

    void* f = Read("out.gr2");
    S("read gr2 -> 0x"); HEX((u32)f); NL();
    if(!f){ S("FAIL read\n"); ExitProcess(1); }
    u32* fi = (u32*)Info(f);
    S("fileinfo -> 0x"); HEX((u32)fi); NL();
    if(!fi){ S("FAIL info\n"); ExitProcess(1); }

    S("\n-- file_info dwords 0..23 --\n");
    for(int i=0;i<24;i++){
        S(" ["); if(i<10) C(' '); DEC((u32)i); S("] 0x"); HEX(fi[i]); S("  "); DEC(fi[i]); NL();
    }

    /* hypothesis: [13]=MeshCount [14]=Meshes**  -- verified by the dump above */
    u32 meshCount = fi[13];
    u32** meshes  = (u32**)fi[14];
    S("\n-- meshes (count="); DEC(meshCount); S(") --\n");
    if(meshCount>0 && meshCount<256 && meshes){
        for(u32 m=0;m<meshCount;m++){
            void* mesh = meshes[m];
            S(" mesh "); DEC(m); S("  name="); S((const char*)((u32*)mesh)[0]);
            S("\n   vertices="); DEC((u32)VCount(mesh));
            S("  indices="); DEC((u32)ICount(mesh));
            S("  triangles="); DEC((u32)TCount(mesh)); NL();
            void* vt = VType(mesh);
            S("   vertexType=0x"); HEX((u32)vt); S("  -> ");
            const char* hit=0;
            for(int k=0; VTNAMES[k]; k++){
                void* p = GetProcAddress(g, VTNAMES[k]);
                if(p && p==vt){ hit=VTNAMES[k]; break; }
            }
            S(hit?hit:"(not a standard exported type)"); NL();
            /* walk the vertex type definition: 32-byte members, Type==0 ends */
            {
                u32* t=(u32*)vt; u32 off=0;
                S("   layout:\n");
                for(int q=0;q<24 && t[0]!=0;q++){
                    u32 ty=t[0]; const char* nm=(const char*)t[1]; u32 aw=t[3];
                    u32 sz = (ty==9||ty==10)?4:((ty==11||ty==12)?2:((ty==13||ty==14)?1:4));
                    if(aw==0) aw=1;
                    S("     +"); DEC(off); S("  type="); DEC(ty);
                    S(" width="); DEC(aw); S("  "); S(nm?nm:"(null)"); NL();
                    off += sz*aw;
                    t += 8;
                }
                S("   my-computed off = "); DEC(off); S(" bytes\n");
                S("   AUTHORITATIVE GrannyGetTotalObjectSize = "); DEC((u32)TotSz(vt)); S(" bytes\n");
                S("   bytesPerIndex = "); DEC((u32)BPI(mesh)); NL();
                { u32* tt=(u32*)vt; S("   per-member GrannyGetMemberTypeSize:\n");
                  for(int q=0;q<12 && tt[0]!=0; q++){ S("     "); S((const char*)tt[1]);
                    S(" = "); DEC((u32)MemSz((void*)tt)); S(" bytes\n"); tt+=8; } }
            }
            float* v = (float*)VVerts(mesh);
            if(v){
                S("   first 3 floats: ");
                FLT(v[0]); C(' '); FLT(v[1]); C(' '); FLT(v[2]); NL();
            }
        }
    } else S(" (mesh count/pointer failed the sanity check -- read the dump)\n");

    S("done\n");
    ExitProcess(0);
}
