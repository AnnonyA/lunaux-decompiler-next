#!/usr/bin/env python3
"""Generate test Luau bytecode files for testing LunaUX decompiler."""

import struct
from pathlib import Path


def _varuint(value: int) -> bytes:
    """Encode an integer as a variable-length unsigned integer."""
    result = []
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result)


def create_simple_print_bytecode() -> bytes:
    """Create simple bytecode: print("Hello from LunaUX")"""
    data = bytearray((8, 2))  # Header: version 8, format 2
    
    # String table
    strings = [b'print', b'Hello from LunaUX!']
    data += _varuint(len(strings))
    for s in strings:
        data += _varuint(len(s)) + s
    
    data += b'\x00'  # End of string table (no userdata types)
    
    # Proto count - 1 proto
    data += _varuint(1)
    
    # Main proto
    proto = bytearray()
    proto += _varuint(4)  # Max stack size
    
    # Instructions
    instructions = [
        # LOADK r0, K0 (load "print")
        (0x04, 0x01, 0x00, 0x00),
        # GETGLOBAL r1, K1 (load _G.print via import)
        (0x04, 0x02, 0x01, 0x01),
        # MOVE r2, r0 (move "Hello..." to r2)
        (0x00, 0x04, 0x02, 0x00),
        # CALL r1, 2, 1 (call print with 1 arg)
        (0x01, 0x01, 0x01, 0x02),
        # RETURN r0, 1
        (0x01, 0x00, 0x01, 0x00),
    ]
    
    data += _varuint(len(instructions))
    for inst in instructions:
        # Encode as little-endian 32-bit word
        word = (inst[0] << 24) | (inst[1] << 16) | (inst[2] << 8) | inst[3]
        proto += struct.pack('<I', word)
    
    # Constants
    proto += _varuint(2)  # 2 constants
    # K0: "print"
    proto += b'\x03' + _varuint(len(strings[0])) + strings[0]
    # K1: "Hello from LunaUX!"
    proto += b'\x03' + _varuint(len(strings[1])) + strings[1]
    
    # Prototypes (none)
    proto += _varuint(0)
    
    # Upvalues (none)
    proto += _varuint(0)
    
    # Debug name
    proto += _varuint(4) + b'main'
    
    # Line info (minimal)
    proto += b'\x00'
    proto += b'\x00'
    
    # Typed locals (none)
    proto += _varuint(0)
    
    data += _varuint(len(proto))
    data += proto
    
    # Main proto index (0 = first and only proto)
    data += _varuint(0)
    
    # Upvalue references (none)
    data += _varuint(0)
    
    return bytes(data)


def create_getservice_bytecode() -> bytes:
    """Create bytecode with GetService pattern: game:GetService("ReplicatedStorage")"""
    data = bytearray((8, 2))
    
    # String table
    strings = [b'game', b'GetService', b'ReplicatedStorage']
    data += _varuint(len(strings))
    for s in strings:
        data += _varuint(len(s)) + s
    
    data += b'\x00'
    data += _varuint(1)
    
    proto = bytearray()
    proto += _varuint(4)
    
    # Simplified instruction sequence
    instructions = [
        # GETGLOBAL r0, K0 (load game)
        (0x04, 0x01, 0x00, 0x00),
        # LOADK r1, K1 (load "GetService")
        (0x04, 0x02, 0x01, 0x01),
        # LOADK r2, K2 (load "ReplicatedStorage")
        (0x04, 0x03, 0x02, 0x02),
        # NAMECALL r0, r0, r1 (prepare method call)
        (0x5C, 0x01, 0x00, 0x01),
        # CALL r0, 3, 1 (call GetService)
        (0x01, 0x01, 0x01, 0x03),
        # RETURN r0, 1
        (0x01, 0x00, 0x01, 0x00),
    ]
    
    data += _varuint(len(instructions))
    for inst in instructions:
        word = (inst[0] << 24) | (inst[1] << 16) | (inst[2] << 8) | inst[3]
        proto += struct.pack('<I', word)
    
    proto += _varuint(3)
    for s in strings:
        proto += b'\x03' + _varuint(len(s)) + s
    
    proto += _varuint(0)
    proto += _varuint(0)
    proto += _varuint(4) + b'main'
    proto += b'\x00'
    proto += b'\x00'
    proto += _varuint(0)
    
    data += _varuint(len(proto))
    data += proto
    data += _varuint(0)  # Main proto index
    
    return bytes(data)


def create_waitforchild_bytecode() -> bytes:
    """Create bytecode with WaitForChild pattern: script:WaitForChild("Part")"""
    data = bytearray((8, 2))
    
    strings = [b'script', b'WaitForChild', b'Part']
    data += _varuint(len(strings))
    for s in strings:
        data += _varuint(len(s)) + s
    
    data += b'\x00'
    data += _varuint(1)
    
    proto = bytearray()
    proto += _varuint(4)
    
    instructions = [
        # GETGLOBAL r0, K0 (load script)
        (0x04, 0x01, 0x00, 0x00),
        # LOADK r1, K1 (load "WaitForChild")
        (0x04, 0x02, 0x01, 0x01),
        # LOADK r2, K2 (load "Part")
        (0x04, 0x03, 0x02, 0x02),
        # NAMECALL r0, r0, r1
        (0x5C, 0x01, 0x00, 0x01),
        # CALL r0, 3, 1
        (0x01, 0x01, 0x01, 0x03),
        # RETURN r0, 1
        (0x01, 0x00, 0x01, 0x00),
    ]
    
    data += _varuint(len(instructions))
    for inst in instructions:
        word = (inst[0] << 24) | (inst[1] << 16) | (inst[2] << 8) | inst[3]
        proto += struct.pack('<I', word)
    
    proto += _varuint(3)
    for s in strings:
        proto += b'\x03' + _varuint(len(s)) + s
    
    proto += _varuint(0)
    proto += _varuint(0)
    proto += _varuint(4) + b'main'
    proto += b'\x00'
    proto += b'\x00'
    proto += _varuint(0)
    
    data += _varuint(len(proto))
    data += proto
    data += _varuint(0)
    
    return bytes(data)


def create_require_bytecode() -> bytes:
    """Create bytecode with Require pattern: local mod = require(script.Parent)"""
    data = bytearray((8, 2))
    
    strings = [b'require', b'Parent', b'script']
    data += _varuint(len(strings))
    for s in strings:
        data += _varuint(len(s)) + s
    
    data += b'\x00'
    data += _varuint(1)
    
    proto = bytearray()
    proto += _varuint(4)
    
    instructions = [
        # GETGLOBAL r0, K0 (load require)
        (0x04, 0x01, 0x00, 0x00),
        # GETGLOBAL r1, K2 (load script)
        (0x04, 0x02, 0x01, 0x02),
        # GETTABLEKS r1, r1, K1 (load script.Parent)
        (0x3C, 0x03, 0x01, 0x01),
        # MOVE r2, r1
        (0x00, 0x04, 0x02, 0x01),
        # CALL r0, 2, 2 (call require with 1 arg, 1 result)
        (0x01, 0x01, 0x01, 0x02),
        # RETURN r0, 2
        (0x01, 0x00, 0x02, 0x00),
    ]
    
    data += _varuint(len(instructions))
    for inst in instructions:
        word = (inst[0] << 24) | (inst[1] << 16) | (inst[2] << 8) | inst[3]
        proto += struct.pack('<I', word)
    
    proto += _varuint(3)
    for s in strings:
        proto += b'\x03' + _varuint(len(s)) + s
    
    proto += _varuint(0)
    proto += _varuint(0)
    proto += _varuint(4) + b'main'
    proto += b'\x00'
    proto += b'\x00'
    proto += _varuint(0)
    
    data += _varuint(len(proto))
    data += proto
    data += _varuint(0)
    
    return bytes(data)


def main():
    output_dir = Path('/tmp/lunaux_tests')
    output_dir.mkdir(exist_ok=True)
    
    tests = [
        ('simple_print.luac', create_simple_print_bytecode, 'Print statement'),
        ('getservice.luac', create_getservice_bytecode, 'GetService pattern'),
        ('waitforchild.luac', create_waitforchild_bytecode, 'WaitForChild pattern'),
        ('require.luac', create_require_bytecode, 'Require pattern'),
    ]
    
    for filename, func, description in tests:
        output_path = output_dir / filename
        output_path.write_bytes(func())
        print(f'✓ {description}: {output_path}')
    
    print(f'\n{len(tests)} archivos de bytecode generados en {output_dir}')
    print('\nPara probar:')
    print(f'  python -m lunaux decompile {output_dir}/simple_print.luac')
    print(f'  python -m lunaux decompile {output_dir}/getservice.luac')


if __name__ == '__main__':
    main()
