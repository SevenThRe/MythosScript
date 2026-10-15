import importlib.util
import pathlib
import struct
import unittest
spec=importlib.util.spec_from_file_location('observer', pathlib.Path(__file__).with_name('observe.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def packed(x,y,z):return struct.pack('>Q',((x&0x3ffffff)<<38)|((y&4095)<<26)|(z&0x3ffffff))
def vi(n):
 out=bytearray()
 while True:
  b=n&127;n>>=7;out.append(b|(128 if n else 0))
  if not n:return bytes(out)
class PacketDecodeTest(unittest.TestCase):
 def test_negative_legacy_position_and_air(self):
  p={'class':'SPacketBlockChange','hex':(packed(-123,64,-7)+vi(0)).hex()}
  self.assertEqual(m.decode(p),[{'kind':'update','pos':(-123,64,-7),'stateId':0}])
 def test_multi_chunk_local_axes(self):
  data=struct.pack('>ii',-2,3)+vi(2)+struct.pack('>H',(15<<12)|(2<<8)|70)+vi(300)+struct.pack('>H',71)+vi(0)
  updates=m.decode({'class':'SPacketMultiBlockChange','hex':data.hex()})
  self.assertEqual(updates[0],{'kind':'update','pos':(-17,70,50),'stateId':300})
  self.assertEqual(updates[1]['pos'],(-32,71,48))
 def test_outgoing_main_and_offhand(self):
  for hand in (0,1):
   row=m.decode({'class':'CPacketPlayerTryUseItemOnBlock','hex':(packed(9,128,10)+vi(1)+vi(hand)+bytes(12)).hex()})[0]
   self.assertEqual((row['pos'],row['hand']),((9,128,10),hand))
 def test_truncated_packets_are_not_updates(self):
  with self.assertRaises((ValueError,struct.error)):m.decode({'class':'SPacketBlockChange','hex':'01'})
  with self.assertRaises(ValueError):m.varint(bytes([128])*6,0)
 def test_named_sequence_read_is_forwarded(self):
  runtime=object.__new__(m.Runtime);runtime.serial=0
  class Client:
   def send(self, message):
    self.message=message
    return {'result':{'structuredContent':{'sequence':{'name':'test'}}}}
  runtime.client=Client()
  result=runtime.call('mythos_paths',operation='get',name='test')
  self.assertEqual(result['sequence']['name'],'test')
  self.assertEqual(runtime.client.message['params']['arguments']['name'],'test')
 def test_native_scripts_only_single_interaction(self):
  import json
  for file in pathlib.Path(__file__).parent.glob('*_单次.json'):
   seq=json.loads(file.read_text(encoding='utf-8'))['sequence'];actions=seq['steps'][0]['actions']
   self.assertEqual(sum(a['type'] in ('click','rightclickblock') for a in actions),1)
   self.assertFalse(any(a['type'] in ('send_packet','goto_label','while_condition') for a in actions))
   self.assertTrue(seq['singleExecution'])
if __name__=='__main__':unittest.main()
