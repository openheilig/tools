import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
public class Impl2 extends GhidraScript {
  Listing L; Map<Function,Integer> callers = new HashMap<>();
  int nCallers(Function f){
    Integer c = callers.get(f);
    if (c!=null) return c;
    Set<Function> s = new HashSet<>();
    for (Reference r : getReferencesTo(f.getEntryPoint())) {
      if (!r.getReferenceType().isCall()) continue;
      Function g = getFunctionContaining(r.getFromAddress());
      if (g!=null) s.add(g);
    }
    callers.put(f, s.size()); return s.size();
  }
  void harvest(Function f, int depth, Set<Function> seen, TreeSet<String> strs, int maxCallers) {
    if (f==null || depth<0 || !seen.add(f)) return;
    List<Function> next = new ArrayList<>();
    InstructionIterator it = L.getInstructions(f.getBody(), true);
    while (it.hasNext()) {
      Instruction I = it.next();
      for (Reference r : I.getReferencesFrom()) {
        Address t = r.getToAddress();
        Data d = L.getDataAt(t);
        if (d!=null && d.hasStringValue()) { String v=d.getValue().toString().trim();
          if (v.length()>3 && v.length()<100) strs.add(v.replace("\n","\\n")); }
        if (r.getReferenceType().isCall()) { Function g=getFunctionAt(t);
          if (g!=null && !g.isThunk() && nCallers(g)<=maxCallers) next.add(g); }
      }
    }
    if (depth>0) for (Function g: next) harvest(g, depth-1, seen, strs, maxCallers);
  }
  public void run() throws Exception {
    L = currentProgram.getListing();
    String[] a = getScriptArgs();
    Address tbl = currentProgram.getAddressFactory().getAddress(a[0]);
    int n=Integer.parseInt(a[1]), depth=Integer.parseInt(a[2]), maxC=Integer.parseInt(a[3]);
    PrintWriter out = new PrintWriter(new FileWriter(a[4]));
    Map<String,List<Integer>> impl = new LinkedHashMap<>();
    for (int i=0;i<n;i++){
      Address t = currentProgram.getAddressFactory().getAddress(String.format("0x%08x", getInt(tbl.add(i*4L)) & 0xffffffffL));
      InstructionIterator it=L.getInstructions(t,true); int k=0; String tgt=null;
      while(it.hasNext() && k++<30){ Instruction I=it.next();
        if (I.getFlowType().isCall()){ Address[] fl=I.getFlows(); if(fl.length>0) tgt=fl[0].toString(); break; }
        if (I.getFlowType().isJump() && !I.getFlowType().isConditional()) break; }
      impl.computeIfAbsent(tgt==null?"none":tgt, x->new ArrayList<>()).add(i);
    }
    for (Map.Entry<String,List<Integer>> e: impl.entrySet()){
      out.println("### " + e.getValue() + " @" + e.getKey());
      if (e.getKey().equals("none")) continue;
      Function f=getFunctionAt(currentProgram.getAddressFactory().getAddress("0x"+e.getKey()));
      TreeSet<String> s=new TreeSet<>();
      harvest(f, depth, new HashSet<>(), s, maxC);
      int i=0; for (String x:s){ if(i++>=14) {out.println("   ..."+(s.size()-14)+" more"); break;} out.println("   "+x); }
    }
    out.close();
  }
}
