# Damage-channel breakpoints for retail sub_81FAC30.
#
#   BPS=analysis/tools/live/bp-damage.gdb ROUTE=load \
#     DISPLAY=:98 timeout 150 sh analysis/tools/live/tohit_bp.sh
#
# 0x81FD08D is `test edi,edi`, immediately before the four per-channel calls
# to the curve at 0x815D44C: every input to the damage step is live there.
#   esi = difficulty index (0..4, from ds:0x8906cd0)
#   edi = the target's creature-info record, or 0
#   [ebp-0x98 .. -0x8c]  four raw damages   (curve a2)
#   [ebp-0xe8 .. -0xdc]  four armour values (curve a3)
#   [ebp-0x2c8]          the level term     (curve a5 = 0.5 * this)
#   [edi + esi + 0x42/0x47/0x4c/0x51]  resist %, 4 channels x 5 difficulties
#   [ebp-0x230] = a1 (the target), [ebp-0x24c] = the attacker cCreature or 0
# 0x81FD1F5 is past the fourth block, where all four results are stored.
set pagination off
set confirm off
set height 0
handle SIGSEGV nostop noprint pass

break *0x81FD08D
commands
silent
printf "IN   diff=%d info=%#x lvlterm=%f\n", $esi, $edi, *(float*)($ebp-0x2c8)
printf "     dmg=[%f %f %f %f]\n", *(float*)($ebp-0x98), *(float*)($ebp-0x94), *(float*)($ebp-0x90), *(float*)($ebp-0x8c)
printf "     arm=[%f %f %f %f]\n", *(float*)($ebp-0xe8), *(float*)($ebp-0xe4), *(float*)($ebp-0xe0), *(float*)($ebp-0xdc)
if $edi != 0
printf "     res=[%d %d %d %d]\n", *(unsigned char*)($edi+$esi+0x42), *(unsigned char*)($edi+$esi+0x47), *(unsigned char*)($edi+$esi+0x4c), *(unsigned char*)($edi+$esi+0x51)
end
printf "     a1=%#x lvl=%d", *(unsigned int*)($ebp-0x230), *(unsigned short*)(*(unsigned int*)($ebp-0x230)+0x56)
if *(unsigned int*)($ebp-0x24c) != 0
printf "  atk=%#x lvl=%d", *(unsigned int*)($ebp-0x24c), *(unsigned short*)(*(unsigned int*)($ebp-0x24c)+0x3fe)
end
printf "\n"
continue
end

break *0x81FD1F5
commands
silent
printf "OUT  [%f %f %f %f]\n", *(float*)($ebp-0x238), *(float*)($ebp-0x23c), *(float*)($ebp-0x240), *(float*)($ebp-0x244)
continue
end

# The no-creature-info path: same four blocks, reached when the lookup failed.
break *0x81FD1FD
commands
silent
printf "IN0  no info record\n"
continue
end
