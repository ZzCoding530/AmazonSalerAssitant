<script setup>
import { ref } from 'vue'

const listingId = ref('L-1001')
const copyText = ref('battery waterproof fast charging lightweight')
const nodeStatus = ref(null)
const strategy = ref([])
const reports = ref([])
const replay = ref(null)
const error = ref('')

async function runPipeline() {
  error.value = ''
  const res = await fetch('/api/pipeline', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      listing_id: listingId.value,
      copy_text: copyText.value,
      profile_version: 'v1',
      copy_version: 'c1',
      rubric_version: 'v1',
      knowledge_version: 's1',
    }),
  })
  const data = await res.json()
  nodeStatus.value = data.node_status
  strategy.value = data.strategy || []
}

async function loadReports() {
  error.value = ''
  const res = await fetch(`/api/listings/${listingId.value}/reports`)
  reports.value = await res.json()
}

async function loadReplay(reportId) {
  const res = await fetch(`/api/reports/${reportId}/replay`)
  replay.value = await res.json()
}
</script>

<template>
  <div class="container">
    <h1>Amazon AdGenie</h1>
    <p class="sub">证据可回溯、评分可校准的广告文案优化策略系统</p>

    <section class="card">
      <h2>触发编排</h2>
      <div class="row">
        <label>Listing ID</label>
        <input v-model="listingId" />
      </div>
      <div class="row">
        <label>广告文案</label>
        <textarea v-model="copyText" rows="3"></textarea>
      </div>
      <button @click="runPipeline">运行 DAG</button>
      <div v-if="nodeStatus" class="result">
        <h3>节点状态</h3>
        <pre>{{ nodeStatus }}</pre>
        <h3>优化策略</h3>
        <ul>
          <li v-for="(s, i) in strategy" :key="i">
            <strong>{{ s.review_id }}</strong> — {{ s.suggestion }}
          </li>
        </ul>
      </div>
    </section>

    <section class="card">
      <h2>评分报告</h2>
      <button @click="loadReports">加载报告</button>
      <table v-if="reports.length">
        <thead>
          <tr>
            <th>report_id</th>
            <th>rubric</th>
            <th>对齐度</th>
            <th>说服力</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reports" :key="r.report_id">
            <td>{{ r.report_id }}</td>
            <td>{{ r.rubric_version }}</td>
            <td>{{ r.alignment_score }}</td>
            <td>{{ r.persuasion_score }}</td>
            <td><button @click="loadReplay(r.report_id)">回放</button></td>
          </tr>
        </tbody>
      </table>
      <pre v-if="replay" class="result">{{ replay }}</pre>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style>
body { font-family: system-ui, sans-serif; background: #f5f6f8; margin: 0; }
.container { max-width: 900px; margin: 24px auto; padding: 0 16px; }
h1 { margin: 0; }
.sub { color: #666; margin-top: 4px; }
.card { background: #fff; border-radius: 8px; padding: 16px; margin-top: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.row { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
.row label { width: 90px; }
input, textarea { flex: 1; padding: 6px; }
button { padding: 8px 16px; background: #1a73e8; color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
th, td { text-align: left; padding: 6px; border-bottom: 1px solid #eee; }
.result { background: #fafafa; padding: 8px; border-radius: 4px; margin-top: 8px; white-space: pre-wrap; }
.error { color: #c00; }
</style>
