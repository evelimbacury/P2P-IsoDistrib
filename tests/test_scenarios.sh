#!/bin/bash

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PASS=0
FAIL=0

check() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}[✓]${NC} $1"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[✗]${NC} $1"
        FAIL=$((FAIL+1))
    fi
}

echo "========== P2P-IsoDistrib Test Suite =========="

# Test 1: Initialization
echo -e "\n[Test 1] Starting containers..."
docker-compose up -d --build
sleep 15
COUNT=$(docker ps --filter "name=p2p_" --format '{{.Names}}' | wc -l)
if [ "$COUNT" -eq 4 ]; then
    check "Test 1: All containers started (4/4)"
else
    echo -e "${RED}[✗] Test 1 failed: $COUNT containers running${NC}"
    FAIL=$((FAIL+1))
fi

# Test 2: Heartbeat
sleep 60
HBS=$(docker logs p2p_tracker 2>&1 | grep -c "Heartbeat")
if [ "$HBS" -ge 3 ]; then
    check "Test 2: Heartbeats detected ($HBS)"
else
    echo -e "${RED}[✗] Test 2 failed: only $HBS heartbeats${NC}"
    FAIL=$((FAIL+1))
fi

# Test 3: Publish
docker exec p2p_peer1 python -c "
from src.peer.network import connect_to_tracker, send_register
import os
sock = connect_to_tracker()
assert sock is not None
send_register(sock, 6000, '/app/shared_files/test_peer1.iso')
print('[Published]')
sock.close()
" | grep -q "Published"
check "Test 3: Publish test_peer1.iso"

# Test 4: Search
docker exec p2p_peer2 python -c "
from src.peer.network import connect_to_tracker, send_lookup
sock = connect_to_tracker()
res = send_lookup(sock, filename='test_peer')
assert res is not None and res['status'] == 'FOUND'
print('[Search] Found:', res['file_info']['name'])
sock.close()
" | grep -q "Found"
check "Test 4: Search for test_peer"

# Test 5: Download (peer3 downloads test_peer1.iso from peer1)
# First, peer3 needs to lookup and download
docker exec p2p_peer3 python -c "
from src.peer.network import connect_to_tracker, send_lookup
from src.peer.file_manager import download_file_parallel
import sys
sock = connect_to_tracker()
res = send_lookup(sock, filename='test_peer1')
if res is None or res['status'] != 'FOUND':
    print('Lookup failed')
    sys.exit(1)
file_info = res['file_info']
peers = res['peers']
if not peers:
    print('No peers')
    sys.exit(1)
path = download_file_parallel(file_info, peers)
if path:
    print('[Success] Downloaded to', path)
else:
    sys.exit(1)
sock.close()
" | grep -q "\[Success\]"
check "Test 5: Download test_peer1.iso"

# Test 6: SHA256 verification
HASH1=$(docker exec p2p_peer1 sha256sum //app//shared_files//test_peer1.iso | awk '{print $1}')
HASH3=$(docker exec p2p_peer3 sha256sum //app//downloads//test_peer1.iso | awk '{print $1}')
if [ "$HASH1" = "$HASH3" ]; then
    check "Test 6: SHA256 match"
else
    echo -e "${RED}[✗] Test 6 failed: hashes differ${NC}"
    FAIL=$((FAIL+1))
fi

# Test 7: Peer Drop
docker stop p2p_peer1
echo "Waiting for tracker to detect dead peer (65s)..."
sleep 65
docker logs p2p_tracker 2>&1 | grep -q "Removed peer"
check "Test 7: Dead peer removed by tracker"
docker start p2p_peer1 >/dev/null

echo -e "\n========== Summary =========="
echo -e "Tests passed: ${GREEN}$PASS${NC}/${PASS+FAIL}"
echo -e "Tests failed: ${RED}$FAIL${NC}/${PASS+FAIL}"

# Uncomment next line to bring everything down
# docker-compose down