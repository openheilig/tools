import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;
public class BalanceMap extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    Function f = getFunctionContaining(currentProgram.getAddressFactory().getAddress(a[0]));
    PrintWriter out = new PrintWriter(new FileWriter(a[1]));
    Listing L = currentProgram.getListing();
    out.println("key\tdest\tstore\tat");
    String key = null; Address keyAt = null;
    InstructionIterator it = L.getInstructions(f.getBody(), true);
    while (it.hasNext()) {
      Instruction I = it.next();
      // remember the last string literal pushed
      for (Reference r : I.getReferencesFrom()) {
        Data d = L.getDataAt(r.getToAddress());
        if (d != null && d.hasStringValue()) {
          String v = d.getValue().toString();
          if (v.length() > 2 && v.length() < 64) { key = v; keyAt = I.getAddress(); }
        }
      }
      String m = I.getMnemonicString();
      boolean store = m.startsWith("FSTP") || m.startsWith("FIST") || m.equals("MOV");
      if (!store || key == null) continue;
      // destination must be an absolute [imm32] operand
      if (I.getNumOperands() < 1) continue;
      Object[] o = I.getOpObjects(0);
      Address dest = null;
      for (Object x : o) {
        if (x instanceof Scalar) { long v = ((Scalar)x).getUnsignedValue();
          if (v >= 0x08048000L && v <= 0x08c00000L) dest = currentProgram.getAddressFactory().getAddress(String.format("0x%08x", v)); }
        if (x instanceof Address) { Address ax=(Address)x;
          if (ax.getOffset()>=0x08048000L && ax.getOffset()<=0x08c00000L) dest = ax; }
      }
      if (dest == null) continue;
      if (m.equals("MOV") && I.getRegister(0) != null) continue;   // reg dest, not a global
      out.println(key + "\t" + dest + "\t" + m + "\t" + I.getAddress());
      key = null;
    }
    out.close();
  }
}
