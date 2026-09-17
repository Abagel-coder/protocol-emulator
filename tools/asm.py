#!/usr/bin/env python3
"""Two-pass assembler for the protocol-emulator ISA (generated tables in tools/isa_defs.py)."""
import argparse, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import isa_defs as D

class AsmError(Exception):
    pass

SYMBOLS = {}
for tbl in (D.REGS, D.BANK_OUT, D.BANK_IN, D.WAITP_COND, D.FLAGS):
    SYMBOLS.update(tbl)
SYMBOLS.update({"UI": D.BANK_IN["UI"], "UOR": D.BANK_IN["UOR"], "UIOR": D.BANK_IN["UIOR"]})
RELATIVE = {"simm9", "simm7", "simm6"}
SIGNED = RELATIVE
TOKEN = re.compile(r"^\s*(?:(?P<label>[A-Za-z_]\w*):)?\s*(?:(?P<op>\.?[A-Za-z_]\w*)\s*(?P<args>[^;]*))?(?:;.*)?$")

def _num(tok, equs, labels):
    tok = tok.strip()
    if tok in equs: return equs[tok]
    if tok in labels: return labels[tok]
    if tok in SYMBOLS: return SYMBOLS[tok]
    try: return int(tok, 0)
    except ValueError: raise AsmError("unknown symbol %r" % tok)

def _place(word, field, value, cls):
    msb, lsb = D.LAYOUTS[cls][field]; width = msb - lsb + 1
    if field in SIGNED:
        lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
        if not lo <= value <= hi: raise AsmError("%s=%d out of range [%d,%d]" % (field, value, lo, hi))
        value &= (1 << width) - 1
    elif not 0 <= value < (1 << width):
        raise AsmError("%s=%d out of range [0,%d]" % (field, value, (1 << width) - 1))
    return word | (value << lsb)

def _parse(text):
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        m = TOKEN.match(raw)
        if not m: raise AsmError("line %d: cannot parse %r" % (n, raw))
        lines.append((n, m.group("label"), (m.group("op") or "").upper(), [a for a in (m.group("args") or "").split(",") if a.strip()]))
    return lines

def assemble(text):
    lines = _parse(text); equs, labels = {}, {}
    pc = 0                                                   # pass 1: addresses
    for n, label, op, args in lines:
        if label: labels[label] = pc
        if op == ".EQU": equs[args[0].split()[0]] = int(args[0].split()[1], 0) if len(args) == 1 else int(args[1], 0)
        elif op == ".ORG": pc = int(args[0], 0)
        elif op in (".WORD",) or op: pc += 1
    words, pc = {}, 0                                        # pass 2: encode
    for n, label, op, args in lines:
        try:
            if op == ".EQU": continue
            if op == ".ORG": pc = int(args[0], 0); continue
            if op == ".WORD": words[pc] = _num(args[0], equs, labels) & 0xFFFF; pc += 1; continue
            if not op: continue
            if op not in D.MNEMONICS: raise AsmError("unknown mnemonic %s" % op)
            spec = D.MNEMONICS[op]; cls = spec["class"]
            if len(args) != len(spec["operands"]): raise AsmError("%s expects %d operands" % (op, len(spec["operands"])))
            word = D.CLASSES[cls] << 12
            for f, v in spec["fixed"].items(): word = _place(word, f, v, cls)
            for f, tok in zip(spec["operands"], args):
                v = _num(tok, equs, labels)
                if f in RELATIVE and tok.strip() in labels: v = labels[tok.strip()] - (pc + 1)
                word = _place(word, f, v, cls)
            words[pc] = word; pc += 1
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e)) from None
    top = max(words) + 1 if words else 0
    return [words.get(i, 0) for i in range(top)]

def assemble_file(path):
    return assemble(open(path).read())

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("src"); ap.add_argument("-o", "--out")
    a = ap.parse_args(); ws = assemble_file(a.src)
    out = "\n".join("%04x" % w for w in ws) + "\n"
    (open(a.out, "w").write(out) if a.out else sys.stdout.write(out))

if __name__ == "__main__":
    main()
