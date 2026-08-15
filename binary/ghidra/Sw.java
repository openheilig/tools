import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
public class Sw extends GhidraScript {
  public void run() throws Exception {
    PrintWriter out = new PrintWriter(new FileWriter("/tmp/gh/out.txt"));
    for (String s : getScriptArgs()) {
      Function f = getFunctionAt(currentProgram.getAddressFactory().getAddress(s));
      out.println("### FUNC " + s + " " + (f==null?"NONE":f.getName()) + " size=" + (f==null?0:f.getBody().getNumAddresses()));
      if (f==null) continue;
      InstructionIterator it = currentProgram.getListing().getInstructions(f.getBody(), true);
      while (it.hasNext()) {
        Instruction ins = it.next();
        if (ins.getFlowType().isComputed() && ins.getFlowType().isJump()) {
          Address[] fl = ins.getFlows();
          Set<Address> u = new TreeSet<>(Arrays.asList(fl));
          out.println("  COMPUTED_JUMP @" + ins.getAddress() + "  " + ins + "  targets=" + fl.length + " distinct=" + u.size());
          StringBuilder sb=new StringBuilder("   ");
          for (Address t : u) sb.append(t).append(" ");
          out.println(sb);
        }
      }
    }
    out.close();
  }
}
