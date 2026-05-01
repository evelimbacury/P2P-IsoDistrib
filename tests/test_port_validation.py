#!/usr/bin/env python3

from src.peer.client import validate_port

def test_port_validation():
    # Test valid ports
    try:
        validate_port('6001')
        print('[✓] Port 6001 accepted')
    except Exception as e:
        print('[✗] Port 6001 rejected:', str(e))

    try:
        validate_port('1')
        print('[✓] Port 1 accepted')
    except Exception as e:
        print('[✗] Port 1 rejected:', str(e))

    try:
        validate_port('65535')
        print('[✓] Port 65535 accepted')
    except Exception as e:
        print('[✗] Port 65535 rejected:', str(e))

    # Test invalid ports
    try:
        validate_port('0')
        print('[✗] Port 0 accepted (should be rejected)')
    except Exception as e:
        print('[✓] Port 0 rejected:', str(e))

    try:
        validate_port('70000')
        print('[✗] Port 70000 accepted (should be rejected)')
    except Exception as e:
        print('[✓] Port 70000 rejected:', str(e))

    try:
        validate_port('abc')
        print('[✗] Port abc accepted (should be rejected)')
    except Exception as e:
        print('[✓] Port abc rejected:', str(e))

if __name__ == '__main__':
    test_port_validation()