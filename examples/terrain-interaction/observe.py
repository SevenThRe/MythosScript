"""Read-only MCP observer for the two native Mythos JSON scripts. Never dispatches gameplay."""
import argparse
import importlib.util
import json
import math
import pathlib
import struct
import time


def varint(data, offset):
    value = 0
    for i in range(5):
        if offset >= len(data):
            raise ValueError('Truncated VarInt')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << (7 * i)
        if not byte & 128:
            return value, offset
    raise ValueError('Oversized VarInt')


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def position(data):
    value = struct.unpack('>Q', data[:8])[0]
    # Minecraft 1.12.2 layout: X26, Y12, Z26 (not the modern X26/Z26/Y12 layout).
    return (signed(value >> 38, 26), signed((value >> 26) & 4095, 12), signed(value & 0x3ffffff, 26))


def decode(packet):
    name = packet.get('class', '').split('.')[-1]
    if name not in ('CPacketPlayerTryUseItemOnBlock', 'SPacketBlockChange', 'SPacketMultiBlockChange'):
        return []
    data = bytes.fromhex(packet['hex'])
    if name == 'CPacketPlayerTryUseItemOnBlock':
        pos = position(data)
        _, offset = varint(data, 8)  # facing
        hand, _ = varint(data, offset)
        return [{'kind': 'interaction', 'pos': pos, 'hand': hand}]
    if name == 'SPacketBlockChange':
        state, _ = varint(data, 8)
        return [{'kind': 'update', 'pos': position(data), 'stateId': state}]
    cx, cz = struct.unpack('>ii', data[:8])
    count, offset = varint(data, 8)
    if count > 65536:
        raise ValueError('Unreasonable multi-block count')
    records = []
    for _ in range(count):
        local = struct.unpack('>H', data[offset:offset + 2])[0]
        offset += 2
        state, offset = varint(data, offset)
        records.append({'kind': 'update', 'pos': (cx * 16 + (local >> 12), local & 255,
                                                  cz * 16 + ((local >> 8) & 15)), 'stateId': state})
    return records


class Runtime:
    def __init__(self, bridge, player=None, pid=None, observe=True):
        spec = importlib.util.spec_from_file_location('mythos_existing_bridge', bridge)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        client = module.LocalClient(auto_discover=True, player=player, pid=pid)
        self.client = module.ObservationClient(client) if observe else client
        self.serial = 0

    def call(self, tool_name, **arguments):
        self.serial += 1
        answer = self.client.send({'jsonrpc': '2.0', 'id': self.serial, 'method': 'tools/call',
                                   'params': {'name': tool_name, 'arguments': arguments}})
        if 'error' in answer:
            raise RuntimeError(answer['error'])
        result = answer.get('result', {})
        value = result.get('structuredContent')
        if value is None:
            value = json.loads(next(c['text'] for c in result.get('content', []) if c.get('type') == 'text'))
        if result.get('isError') or value.get('errorCode') or value.get('available') is False:
            raise RuntimeError(value.get('message', value))
        return value

    def tail(self, direction):
        page = self.call('mythos_packets', operation='list', direction=direction, offset=0, limit=1)
        total = page['total']
        start = max(0, total - 200)
        rows = []
        while start < total:
            page = self.call('mythos_packets', operation='list', direction=direction, offset=start, limit=100)
            rows.extend(page['packets'])
            if page['nextOffset'] <= start:
                break
            start = page['nextOffset']
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--player')
    parser.add_argument('--pid', type=int)
    parser.add_argument('--arm-seconds', type=int, default=90)
    parser.add_argument('--bridge', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2] /
                        'skills/mythosscript-mcp/scripts/client.py')
    parser.add_argument('--install', action='store_true', help='Only hot-load/validate the JSON sequences; never run them')
    args = parser.parse_args()
    runtime = Runtime(args.bridge, args.player, args.pid, observe=not args.install)
    clients = runtime.call('mythos_clients')
    if not clients.get('clients'):
        raise RuntimeError('Game not connected. Start Minecraft first; existing JAR is sufficient.')
    available = [x for x in clients['clients'] if x.get('inWorld')]
    if args.pid is not None:
        available = [x for x in available if x.get('pid') == args.pid]
    if args.player:
        available = [x for x in available if x.get('player') == args.player]
    if len(available) != 1:
        raise RuntimeError('Select one in-world client with --player or --pid.')
    base_client = runtime.client.client if hasattr(runtime.client, 'client') else runtime.client
    base_client.pid = available[0]['pid']
    if args.install:
        for path in sorted(pathlib.Path(__file__).parent.glob('*_单次.json')):
            sequence = json.loads(path.read_text(encoding='utf-8'))['sequence']
            validation = runtime.call('mythos_validate', sequence=sequence)
            print(json.dumps(validation, ensure_ascii=False))
            # The backend also validates before persisting. put updates the in-memory sequence immediately.
            runtime.call('mythos_paths', operation='put', sequence=sequence)
            saved = runtime.call('mythos_paths', operation='get', name=sequence['name'])
            assert saved['sequence']['name'] == sequence['name']
            original_actions = sequence['steps'][0]['actions']
            saved_actions = saved['sequence']['steps'][0]['actions']
            assert len(original_actions) == len(saved_actions)
            for expected, actual in zip(original_actions, saved_actions):
                assert expected['type'] == actual['type']
                assert all(actual['params'].get(k) == v for k, v in expected['params'].items())
            print('已热载入：' + sequence['name'])
        return
    status = runtime.call('mythos_status')
    if not status.get('inWorld'):
        raise RuntimeError('Enter a world before arming.')
    original_capture = status.get('capture', False)
    origin = [math.floor(status['player'][axis]) - 5 for axis in ('x', 'y', 'z')]
    before = runtime.call('mythos_snapshot', groups=['player', 'world'], origin=origin, size=[11, 11, 11])
    seen = set()
    for direction in ('C2S', 'S2C'):
        for packet in runtime.tail(direction):
            seen.add((direction, packet['timestamp'], packet['class'], packet['hex']))
    result = {'status': 'no_interaction', 'hiddenWorldTruthVerified': False,
              'beforeClientSnapshot': before, 'server': status.get('server'),
              'correlation': 'same runtime session, position and time; protocol has no request ID'}
    started = time.monotonic()
    cutoff = int(time.time() * 1000)
    sent = []
    updates = []
    result_dir = pathlib.Path(__file__).parent / 'results'
    result_dir.mkdir(exist_ok=True)
    try:
        if not original_capture:
            runtime.call('mythos_packets', operation='capture_start')
        print('观察器已就绪；现在手动运行一条“方块验证”脚本。不要同时手动右键。', flush=True)
        while time.monotonic() - started < min(120, max(5, args.arm_seconds)):
            for direction in ('C2S', 'S2C'):
                for packet in runtime.tail(direction):
                    key = (direction, packet['timestamp'], packet['class'], packet['hex'])
                    if key in seen or packet['timestamp'] < cutoff:
                        continue
                    seen.add(key)
                    try:
                        decoded = decode(packet)
                    except (ValueError, struct.error):
                        result['packetDecodeErrors'] = result.get('packetDecodeErrors', 0) + 1
                        continue
                    for item in decoded:
                        item.update(timestamp=packet['timestamp'], packet=packet)
                        if direction == 'C2S' and item['kind'] == 'interaction' and item['hand'] == 0:
                            sent.append(item)
                        if direction == 'S2C' and item['kind'] == 'update':
                            updates.append(item)
            current = runtime.call('mythos_snapshot', groups=['player'])
            if (not current.get('inWorld') or current.get('sessionId') != before.get('sessionId') or
                    current.get('player', {}).get('dimension') != before.get('player', {}).get('dimension')):
                result['status'] = 'session_changed_unverified'
                break
            if len(seen) > 10000 or len(updates) > 65536:
                result['status'] = 'capture_budget_exceeded_unverified'
                break
            if len(sent) > 1:
                result['status'] = 'ambiguous_multiple_interactions'
                break
            if sent:
                target = sent[0]
                matches = [x for x in updates if x['pos'] == target['pos'] and
                           target['timestamp'] <= x['timestamp'] <= target['timestamp'] + 5000]
                if matches:
                    result.update(status='server_block_update', interaction=target, update=matches[0])
                    result['afterClientSnapshot'] = runtime.call('mythos_snapshot', groups=['player', 'world'],
                                                                 origin=list(target['pos']), size=[1, 1, 1])
                    break
                if int(time.time() * 1000) - target['timestamp'] > 5000:
                    result.update(status='timeout_unverified', interaction=target)
                    break
            time.sleep(0.25)
    finally:
        if not original_capture:
            try:
                runtime.call('mythos_packets', operation='capture_stop')
            except Exception as error:
                result['captureRestoreError'] = str(error)
        output = result_dir / ('review-' + str(int(time.time() * 1000)) + '.json')
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(result['status'] + '\n' + str(output))


if __name__ == '__main__':
    main()
