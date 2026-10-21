"""No model/native execution: real ledger and archived actual caller controls."""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from experiments import training_ledger_integration as integration
from experiments.trace_ledger import BoundedJSONLLedger,LedgerIOError,LedgerLimitError
from scripts import audit_training_ledger as auditor
from scripts import audit_observer_duty_v2 as legacy

ROOT=Path(__file__).resolve().parents[1]


def fixture(partial=False,**limits):
    sink=io.BytesIO()
    writer=integration.PartialPretrainSink(sink) if partial else sink
    job=mock.Mock()
    ref=mock.Mock(pid=20,creation_filetime=200)
    ref.reading.side_effect=lambda:{"pid":20,"creation_filetime":200,"perf_counter":time.perf_counter(),
        "memory":{"resident_bytes":100,"private_bytes":200}}
    ledger=BoundedJSONLLedger(writer,**(limits or integration.LIMITS))
    trace=integration.TrainingTrace(job,ref,ledger)
    launcher=mock.Mock(pid=10,creation_filetime=100)
    return sink,trace,job,ref,launcher


class TraceControls(unittest.TestCase):
    def setUp(self):
        p=mock.patch.object(integration.work,"native_process_cpu",return_value=1.0)
        p.start();self.addCleanup(p.stop)
        p=mock.patch.object(integration.obs,"WindowsJob",side_effect=AssertionError("No native Job in unit tests"))
        p.start();self.addCleanup(p.stop)

    def test_reads_retained_interpreter_after_current_membership_not_launcher(self):
        sink,t,job,ref,launcher=fixture()
        events=[]
        job.member.side_effect=lambda v:events.append(("member",v.pid))
        original=ref.reading.side_effect
        ref.reading.side_effect=lambda:(events.append(("read",20)),original())[1]
        t.start(launcher)
        sample=t.sample("held:pretrain")
        self.assertEqual(events,[("member",20),("read",20)])
        self.assertEqual(sample["native_cpu_seconds"],1.0)
        self.assertEqual(t.ledger.snapshot()["records"][1]["reading"],sample)
        self.assertNotEqual(sample["pid"],launcher.pid)
        with self.assertRaises(integration.obs.ObserverError):t.start(launcher)

    def test_query_before_binding_rejected(self):
        _,t,job,ref,_=fixture()
        with self.assertRaises(integration.obs.ObserverError):t.sample("early")
        job.member.assert_not_called();ref.reading.assert_not_called()

    def test_membership_or_reading_identity_failure_stops_future_queries(self):
        for failure in ("membership","identity"):
            with self.subTest(failure=failure):
                _,t,job,ref,launcher=fixture();t.start(launcher)
                if failure=="membership":job.member.side_effect=integration.obs.ObserverError("not live/member")
                else:ref.reading.side_effect=lambda:{"pid":10,"creation_filetime":100}
                with self.assertRaises(integration.obs.ObserverError):t.sample("wrong")
                count=job.member.call_count
                with self.assertRaises(integration.obs.ObserverError):t.sample("later")
                self.assertEqual(count,job.member.call_count)
                self.assertEqual(t.ledger.snapshot()["committed_rows"],1)

    def test_real_partial_pretrain_write_preserves_prefix_and_prevents_native_retry(self):
        sink,t,job,_,launcher=fixture(partial=True);t.start(launcher)
        for label in ("preimport","postimport"):t.sample("held:"+label)
        with self.assertRaises(LedgerIOError):t.sample("held:pretrain")
        raw=sink.getvalue();self.assertEqual(raw.rsplit(b"\n",1)[1],b'{"cre')
        before=job.member.call_count
        with self.assertRaises(integration.obs.ObserverError):t.sample("after")
        with self.assertRaises(integration.obs.ObserverError):t.close_record({})
        self.assertEqual(raw,sink.getvalue());self.assertEqual(before,job.member.call_count)

    def test_capacity_refusal_stops_caller_without_poisoning_ledger(self):
        _,t,job,_,launcher=fixture(max_rows=1,max_row_bytes=8192,max_total_bytes=8192);t.start(launcher)
        with self.assertRaises(LedgerLimitError):t.sample("cap")
        self.assertFalse(t.ledger.snapshot()["poisoned"])
        with self.assertRaises(integration.obs.ObserverError):t.sample("later")

    def test_sampled_resource_budget_stops_before_publish(self):
        _,t,_,ref,launcher=fixture();t.start(launcher)
        ref.reading.side_effect=lambda:{"pid":20,"creation_filetime":200,"perf_counter":time.perf_counter(),
            "memory":{"private_bytes":integration.MAX_PRIVATE_BYTES+1,"resident_bytes":1}}
        with self.assertRaises(integration.obs.ObserverError):t.sample("cap")
        self.assertEqual(t.ledger.snapshot()["committed_rows"],1)
        self.assertTrue(t.failed)

    def test_held_caller_does_not_emit_release_after_trace_failure(self):
        _,t,job,actual,launcher=fixture(partial=True);t.start(launcher)
        for label in ("preimport","postimport"):t.sample("held:"+label)
        ready={"pid":20,"stage":"pretrain","native_thread_count":1,"provider_guard":{}}
        report={"samples":[],"parent_query_costs":[]}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(integration.work,"wait_receipt",side_effect=[ready,{}]), \
            mock.patch.object(integration.prior,"validate_provider",return_value=True), \
            mock.patch.object(integration,"inventory") as census, mock.patch.object(integration,"control") as control:
            now=time.perf_counter()
            with self.assertRaises(LedgerIOError):integration.read_held(job,launcher,actual,None,Path(d),"pretrain","n",report,now+60,now+240,trace=t)
            census.assert_not_called();control.assert_not_called()
            self.assertEqual(report["samples"],[])
            self.assertEqual(list(report["stages"]),["pretrain"])

    def test_clean_close_records_after_native_cleanup_and_retires_queries(self):
        _,t,_,_,launcher=fixture();t.start(launcher);t.sample("active:0")
        cleanup={"job_active_count":0,"all_retained_handles_exited":True}
        t.close_record(cleanup)
        self.assertEqual(t.ledger.snapshot()["records"][-1]["cleanup"],cleanup)
        with self.assertRaises(integration.obs.ObserverError):t.sample("late")


class SavedControls(unittest.TestCase):
    def test_real_writer_bytes_and_tail_replay_and_mutations(self):
        for partial in (False,True):
            with mock.patch.object(integration.work,"native_process_cpu",return_value=1.0):
                sink,t,_,ref,launcher=fixture(partial=partial)
                started=time.perf_counter();t.start(launcher)
                brackets={}
                for label in (auditor.STAGES[:2] if partial else auditor.STAGES):
                    brackets[label]={"parent":t.sample("held:"+label)}
                if partial:
                    with self.assertRaises(LedgerIOError):t.sample("held:pretrain")
                else:t.close_record({"job_active_count":0})
                c={"id":"partial_pretrain" if partial else "healthy","ledger":t.ledger.snapshot(),
                    "fault_injected":partial,"worker_identity":{"self_receipt":{"pid":ref.pid,"creation_filetime":ref.creation_filetime}},
                    "launcher":{"pid":launcher.pid},"memory_brackets":brackets,"active_window":{"observations":[]},
                    "started_perf_counter":started,"completed_perf_counter":time.perf_counter(),"cleanup":{"job_active_count":0}}
                raw=sink.getvalue();self.assertGreater(auditor.ledger_checks(c,raw)["samples"],0)
                for wrong in (raw+b"x",raw[:-1],raw.replace(b'"pid":20',b'"pid":10',1)):
                    with self.assertRaises(AssertionError):auditor.ledger_checks(c,wrong)

    def test_partial_roles_prefix_accepts_archive_but_rejects_unregistered_identity(self):
        r,f,c=self.archive()
        c["censuses"]=c["censuses"][:3];c["role_decisions"]=c["role_decisions"][:3]
        _,checks=auditor.replay_partial_roles(c,f,c["started_perf_counter"],c["completed_perf_counter"])
        self.assertTrue(all(v["passed"] for v in checks))
        c["censuses"][-1]["processes"][-1]["pid"]+=100000
        try:
            _,checks=auditor.replay_partial_roles(c,f,c["started_perf_counter"],c["completed_perf_counter"])
        except (KeyError,AssertionError):return
        self.assertTrue(any(not v["passed"] for v in checks))

    def archive(self):
        report=json.loads((ROOT/"results/observer-duty-v2/report.json").read_bytes())
        freeze=json.loads((ROOT/"fixtures/observer-duty-v2/implementation.json").read_bytes())
        c=copy.deepcopy(report["cases"][1]);c["id"]="healthy"
        return report,freeze,c

    def test_independent_healthy_replay_accepts_archived_actual_caller(self):
        r,f,c=self.archive()
        checks=auditor.healthy(c,f,legacy.raw_payloads(c),r["started_perf_counter"],r["completed_perf_counter"],legacy.stamp(r["started_at"]),legacy.stamp(r["completed_at"]))
        self.assertGreater(len(checks),1000)
        self.assertEqual([v for v in checks if not v["passed"]],[])

    def test_archived_ack_or_provider_mutation_is_rejected(self):
        for mutation in ("ack","provider","pid"):
            r,f,c=self.archive()
            if mutation=="ack":c["postvalidation_continue_ack_barrier"]["accepted_receipt"]["pid"]+=1
            elif mutation=="provider":c["stages"]["pretrain"]["provider_guard"]["allowed_local_probe_count"]=0
            else:c["memory_brackets"]["pretrain"]["parent"]["pid"]+=1
            checks=auditor.healthy(c,f,legacy.raw_payloads(c),r["started_perf_counter"],r["completed_perf_counter"],legacy.stamp(r["started_at"]),legacy.stamp(r["completed_at"]))
            self.assertTrue(any(not v["passed"] for v in checks),mutation)


if __name__=="__main__":unittest.main()
