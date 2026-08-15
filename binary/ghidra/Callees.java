// For each entry of a jump table, the NAMED functions its handler reaches.
//
// Impl2.java harvests the strings a handler can reach; this harvests the
// symbols. Once the vtable names are imported (ImportNames.java) roughly 2200
// engine methods carry a class and slot, so a handler that reaches
// cWeapon3D::vf18 or cCreature::vf07 has told you which subsystem it drives
// even when it contains no string at all.
//
// A callee with many callers is a shared utility and says nothing about the
// caller, so `maxcallers` drops those -- the same filter Impl2 uses, and the
// only reason the output is signal rather than a list of std:: and operator
// new. Class names are counted as well as listed: the class a handler touches
// most is usually the one it is about.
//
// Args: <table-addr> <n-entries> <depth> <maxcallers> <out.tsv>
// Out:  index<TAB>trampoline<TAB>impl<TAB>ndistinct<TAB>top classes<TAB>named callees
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.mem.*;
import java.io.*;
import java.util.*;

public class Callees extends GhidraScript {
  Listing L;
  Map<Function, Integer> callers = new HashMap<>();

  int nCallers(Function f) {
    Integer c = callers.get(f);
    if (c != null) return c;
    Set<Function> s = new HashSet<>();
    for (Reference r : getReferencesTo(f.getEntryPoint())) {
      if (!r.getReferenceType().isCall()) continue;
      Function g = getFunctionContaining(r.getFromAddress());
      if (g != null) s.add(g);
    }
    callers.put(f, s.size());
    return s.size();
  }

  static boolean named(Function f) {
    String n = f.getName();
    return !n.startsWith("FUN_") && !n.startsWith("thunk_") && !n.startsWith("_");
  }

  void harvest(Function f, int depth, Set<Function> seen, TreeSet<String> out,
               Map<String, Integer> cls, int maxCallers) {
    if (f == null || depth < 0 || !seen.add(f)) return;
    List<Function> next = new ArrayList<>();
    InstructionIterator it = L.getInstructions(f.getBody(), true);
    while (it.hasNext()) {
      Instruction I = it.next();
      for (Reference r : I.getReferencesFrom()) {
        if (!r.getReferenceType().isCall()) continue;
        Function g = getFunctionAt(r.getToAddress());
        if (g == null || g.isThunk() || nCallers(g) > maxCallers) continue;
        if (named(g)) {
          out.add(g.getName());
          int i = g.getName().indexOf("__");
          if (i > 0) cls.merge(g.getName().substring(0, i), 1, Integer::sum);
        }
        next.add(g);
      }
    }
    if (depth > 0) for (Function g : next) harvest(g, depth - 1, seen, out, cls, maxCallers);
  }

  public void run() throws Exception {
    L = currentProgram.getListing();
    String[] a = getScriptArgs();
    Address tbl = currentProgram.getAddressFactory().getAddress(a[0]);
    int n = Integer.parseInt(a[1]), depth = Integer.parseInt(a[2]);
    int maxCallers = Integer.parseInt(a[3]);
    PrintWriter w = new PrintWriter(new FileWriter(a[4]));
    w.println("index\ttrampoline\timpl\tndistinct\tclasses\tnamed_callees");
    Memory mem = currentProgram.getMemory();
    for (int i = 0; i < n; i++) {
      Address t = tbl.add(4L * i);
      Address dest = currentProgram.getAddressFactory()
          .getDefaultAddressSpace().getAddress(mem.getInt(t) & 0xffffffffL);
      // the trampoline usually does nothing but call the real handler
      Function impl = null;
      Function tramp = getFunctionContaining(dest);
      InstructionIterator it = L.getInstructions(
          new AddressSet(dest, dest.add(0x40)), true);
      while (it.hasNext() && impl == null) {
        for (Reference r : it.next().getReferencesFrom())
          if (r.getReferenceType().isCall()) {
            Function g = getFunctionAt(r.getToAddress());
            if (g != null) { impl = g; break; }
          }
      }
      Function root = impl != null ? impl : tramp;
      TreeSet<String> out = new TreeSet<>();
      Map<String, Integer> cls = new HashMap<>();
      harvest(root, depth, new HashSet<>(), out, cls, maxCallers);
      List<Map.Entry<String, Integer>> top = new ArrayList<>(cls.entrySet());
      top.sort((x, y) -> y.getValue() - x.getValue());
      StringBuilder cs = new StringBuilder();
      for (int k = 0; k < Math.min(3, top.size()); k++)
        cs.append(k > 0 ? "," : "").append(top.get(k).getKey())
          .append(":").append(top.get(k).getValue());
      w.printf("%d\t%s\t%s\t%d\t%s\t%s%n", i, dest,
               root == null ? "-" : root.getEntryPoint().toString(),
               out.size(), cs, String.join(" ", out));
    }
    w.close();
    println("Callees: " + n + " entries -> " + a[4]);
  }
}
