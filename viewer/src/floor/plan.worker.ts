// The layout worker: plans one floor per message (factory/plan-job.ts), off the page's main thread.
import { planWorkerState } from "../factory/plan-job";

const st = planWorkerState();
self.onmessage = (e: MessageEvent) => { const r = st.handle(e.data); if (r) self.postMessage(r); };
