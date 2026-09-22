#!/usr/bin/env python3
"""Two-pass assembler for the protocol-emulator ISA (generated tables in tools/isa_defs.py).

Syntax: one statement per line, `label:` prefix optional, `;` starts a comment, operands are
comma-separated. Numbers are Python literals (`0x`, `0b`, `0o` prefixes; decimal without a
leading zero); registers/banks/conditions/flags by the names in isa/isa.yaml (upper case).
Directives: `.equ NAME VALUE` (or `NAME, VALUE`; the value is a numeric literal), `.org ADDRESS`
(a numeric literal, forwards only), `.word VALUE` (a literal, `.equ` name or label; -32768..65535,
stored as 16 bits). A label used as a branch operand (BR/BPIN/BFLAG classes) assembles as a
pc-relative offset; anywhere else (ADDI, .word, JMP/CALL) a label is its absolute address.

Program size: the core's PC is PC_BITS wide, and core v0's instruction memory holds IMEM_WORDS
(64) words -- addresses and jump targets alias modulo 64 on the chip (docs/info.md), so a
program that does not fit is an error rather than a silently wrapped image. Pass
`max_words=None` to assemble beyond 64 words (up to the 10-bit PC) for other memory sizes.
"""
import argparse, re, sys, os
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import isa_defs as D

class AsmError(Exception):
    pass

IMEM_WORDS = 64                                   # core v0 instruction memory (src/pe_imem_ff.v WORDS)
PC_LIMIT = 1 << D.PC_BITS                         # the ISA's 10-bit PC: the hard limit for any memory size

SYMBOLS = {}
for tbl in (D.REGS, D.BANK_OUT, D.BANK_IN, D.WAITP_COND, D.FLAGS):
    SYMBOLS.update(tbl)
SYMBOLS.update({"UI": D.BANK_IN["UI"], "UOR": D.BANK_IN["UOR"], "UIOR": D.BANK_IN["UIOR"]})
SIGNED = {"simm9", "simm7", "simm6"}              # two's-complement fields (range-checked as signed)
RELATIVE_CLASSES = {"BR", "BPIN", "BFLAG"}        # classes whose signed field is a pc-relative branch offset
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

def _one_arg(op, args):
    if len(args) != 1: raise AsmError("%s expects exactly one argument" % op.lower())
    return args[0]

def _int(tok, what):
    """A plain numeric literal (no symbols: .org and .equ values are numbers in v0)."""
    try: return int(tok.strip(), 0)
    except ValueError: raise AsmError("%s must be a number, got %r" % (what, tok.strip()))

def _org(args, pc, max_words):
    """Resolve an .org target (a numeric literal), checking it is a real, forward address."""
    new_pc = _int(_one_arg(".org", args), ".org address")
    if new_pc < pc: raise AsmError(".org 0x%x moves backwards from 0x%x" % (new_pc, pc))
    limit = PC_LIMIT if max_words is None else max_words
    if not 0 <= new_pc < limit:
        raise AsmError(".org 0x%x is outside the %d-word instruction memory (addresses 0..%d)" % (new_pc, limit, limit - 1))
    return new_pc

def assemble(text, max_words=IMEM_WORDS):
    """Assemble `text` into a list of 16-bit words (index = address). Raises AsmError (with the
    source line number) for anything malformed, out of range, or larger than `max_words`
    (None: only the PC width limits it)."""
    if max_words is not None and not 0 < max_words <= PC_LIMIT:
        raise ValueError("max_words must be in 1..%d or None" % PC_LIMIT)
    limit = PC_LIMIT if max_words is None else max_words
    lines = _parse(text); equs, labels = {}, {}
    pc = 0; max_pc = 0                                       # pass 1: addresses
    for n, label, op, args in lines:
        try:
            if label:
                if label in labels: raise AsmError("duplicate label %r" % label)
                labels[label] = pc
            if op == ".EQU":
                if len(args) == 1:
                    parts = args[0].split()
                    if len(parts) != 2: raise AsmError(".equ expects NAME VALUE or NAME, VALUE")
                    equs[parts[0]] = _int(parts[1], ".equ value")
                elif len(args) == 2:
                    equs[args[0].strip()] = _int(args[1], ".equ value")
                else:
                    raise AsmError(".equ expects NAME VALUE or NAME, VALUE")
            elif op == ".ORG":
                pc = _org(args, pc, max_words)
            elif op != "":
                pc += 1
            max_pc = max(max_pc, pc)
            if max_pc > limit:
                raise AsmError("program does not fit: address 0x%x is beyond the %d-word instruction memory" % (pc - 1, limit))
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e)) from None
    words, pc = {}, 0                                        # pass 2: encode (addresses are strictly increasing, pass 1 checked .org)
    for n, label, op, args in lines:
        try:
            if op == ".EQU": continue
            if op == ".ORG":
                pc = _org(args, pc, max_words); continue
            if op == ".WORD":
                v = _num(_one_arg(".word", args), equs, labels)
                if not -0x8000 <= v <= 0xFFFF: raise AsmError(".word value %d does not fit in 16 bits" % v)
                words[pc] = v & 0xFFFF; pc += 1; continue
            if not op: continue
            if op not in D.MNEMONICS: raise AsmError("unknown mnemonic %s" % op)
            spec = D.MNEMONICS[op]; cls = spec["class"]
            if len(args) != len(spec["operands"]): raise AsmError("%s expects %d operands" % (op, len(spec["operands"])))
            word = D.CLASSES[cls] << 12
            for f, v in spec["fixed"].items(): word = _place(word, f, v, cls)
            for f, tok in zip(spec["operands"], args):
                v = _num(tok, equs, labels)
                if cls in RELATIVE_CLASSES and f in SIGNED and tok.strip() in labels: v = labels[tok.strip()] - (pc + 1)
                word = _place(word, f, v, cls)
            words[pc] = word; pc += 1
        except AsmError as e:
            raise AsmError("line %d: %s" % (n, e)) from None
    top = max(words) + 1 if words else 0
    return [words.get(i, 0) for i in range(top)]

def assemble_file(path, max_words=IMEM_WORDS):
    with open(path) as f:
        return assemble(f.read(), max_words=max_words)

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src"); ap.add_argument("-o", "--out")
    ap.add_argument("--max-words", type=int, default=IMEM_WORDS, help="instruction memory size to check against (default %d; 0 = only the %d-bit PC)" % (IMEM_WORDS, D.PC_BITS))
    a = ap.parse_args()
    try:
        ws = assemble_file(a.src, max_words=(a.max_words or None))
    except AsmError as e:
        sys.exit("%s: %s" % (a.src, e))
    out = "\n".join("%04x" % w for w in ws) + "\n"
    if a.out:
        with open(a.out, "w") as f:
            f.write(out)
    else:
        sys.stdout.write(out)

if __name__ == "__main__":
    main()
