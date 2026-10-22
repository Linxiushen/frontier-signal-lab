import copy
import json
from pathlib import Path
import tempfile
import unittest
from experiments import native_training_cost as s


class NativeTrainingCostTest(unittest.TestCase):
    def test_original_unrescued_workload(self):
        self.assertEqual(s.CONFIG,s.cost.preset_config())
        self.assertEqual([j['seed']for j in s.jobs()],[503,503,701,701,907,907]*2)
        self.assertEqual(len(s.jobs()),12)
        for j in s.jobs():self.assertEqual(s.require_job(j),j)
        for key,value in [('seed',42),('method','dense-new'),('id','duplicate')]:
            bad=copy.deepcopy(s.jobs()[0]);bad[key]=value
            with self.assertRaises(ValueError):s.require_job(bad)

    def test_release_requires_every_fixed_endpoint_and_exact_checkpoint(self):
        with tempfile.TemporaryDirectory()as tmp:
            root=Path(tmp);endpoints=[]
            for j in s.jobs():
                folder=root/j['id'];folder.mkdir();p=folder/'endpoint.pt';p.write_bytes(j['id'].encode())
                endpoints.append({'job':j,'checkpoint_sha256':s.cost.file_hash(p),'initial_parameter_sha256':'a'*64,'final_parameter_sha256':'b'*64})
            release={'id':s.ID,'all_training_completed':True,'training_sealed_at':'2026-10-22T00:00:00Z','protocol_sha256':'c'*64,'endpoints':endpoints}
            self.assertEqual(len(s.validate_release(release,root)),12)
            for mutate in [lambda r:r['endpoints'].pop(),lambda r:r['endpoints'].reverse(),lambda r:r['endpoints'].__setitem__(1,r['endpoints'][0]),lambda r:r.update(all_training_completed=False)]:
                bad=copy.deepcopy(release);mutate(bad)
                with self.assertRaises(ValueError):s.validate_release(bad,root)
            (root/s.jobs()[0]['id']/'endpoint.pt').write_bytes(b'changed')
            with self.assertRaises(ValueError):s.validate_release(release,root)

    def test_train_holdout_open_is_refused(self):
        for name in ['holdout.json','C:/data/holdout.json',b'C:\\data\\holdout.json',Path('holdout.json')]:
            with self.assertRaises(PermissionError):s.refuse_holdout('open',(name,'r',0))
        for name in ['train.json',3,'holdout.json.bak']:s.refuse_holdout('open',(name,'r',0))

    def test_latency_counts_all_phases_and_tail_order_statistic(self):
        rows=[dict(index=i,data_seconds=.1,zero_grad_seconds=.2,forward_seconds=.3,backward_seconds=.4,optimizer_seconds=.5,loss_record_seconds=.6,wall_seconds=2.1)for i in range(20)]
        self.assertEqual(s.summarize_steps(rows)['count'],20)
        self.assertEqual(s.quantile(list(range(1,21)),.95),19)
        self.assertEqual(s.quantile(list(range(1,21)),.99),20)
        for key,value in [('index',9),('forward_seconds',float('nan')),('wall_seconds',3)]:
            bad=copy.deepcopy(rows);bad[0][key]=value
            with self.assertRaises(ValueError):s.summarize_steps(bad)

    def test_large_receipt_is_published_after_complete_serialization(self):
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'loop.json';value={'phases':list(range(10000))}
            s.publish_json(p,value)
            self.assertEqual(json.loads(p.read_bytes()),value)
            self.assertFalse(p.with_suffix('.json.pending').exists())
            with self.assertRaises(FileExistsError):s.publish_json(p,{'bad':True})
            self.assertEqual(json.loads(p.read_bytes()),value)


if __name__=='__main__':unittest.main()
