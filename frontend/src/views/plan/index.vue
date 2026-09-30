<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>点检计划管理</h2>
        <p class="page-desc">维护点检计划，围绕计划编号、点检对象、点检周期、点检项目做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记点检计划</button>
        <button class="btn" type="button" @click="exportRows">导出点检计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div class="batch-bar">
      <label class="filter-item">
        <span>审批人员</span>
        <input v-model="approver" placeholder="指定审批人，可留空" />
      </label>
      <button
        class="btn primary"
        type="button"
        :disabled="!selectedIds.length || submitting"
        @click="submitBatch"
      >
        批量送审（已标记 {{ selectedIds.length }} 张）
      </button>
      <span class="batch-tip">仅「待编制」的计划可标记；点检周期或计划工期没填全的会被自动挑出，不随批送审。</span>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="check-col">
            <input
              type="checkbox"
              :checked="allChecked"
              :disabled="!eligibleIds.length"
              title="标记本页全部待送审计划"
              @change="toggleAll"
            />
          </th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td class="check-col">
            <input
              type="checkbox"
              :checked="isSelected(row)"
              :disabled="!isSubmittable(row)"
              :title="isSubmittable(row) ? '标记送审' : '当前状态不可送审'"
              @change="toggleRow(row)"
            />
          </td>
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无点检计划数据，可先登记点检计划</td>
        </tr>
      </tbody>
    </table>

    <section v-if="receipts.length" class="receipt-panel">
      <header class="receipt-head">
        <strong>送审回执</strong>
        <span>{{ batchMessage }}</span>
      </header>
      <ul class="receipt-list">
        <li v-for="item in receipts" :key="item.id" class="receipt-item" :class="item.category">
          <span class="receipt-code">{{ item['计划编号'] || `#${item.id}` }}</span>
          <span class="receipt-message">{{ item.message }}</span>
        </li>
      </ul>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条点检计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>

type Receipt = {
  id: number
  ok: boolean
  category: 'submitted' | 'duplicated' | 'skipped' | 'failed'
  message: string
  '计划编号'?: string | null
}

type BatchResponse = {
  ok: boolean
  message: string
  results?: Receipt[]
}

const ENDPOINT = '/api/plan'
const columns = ["计划编号", "点检对象", "点检周期", "点检项目", "计划工期", "编制人员", "审批人员", "计划状态"]
const actions = ["提交审批", "确认批复", "作废计划"]
const SUBMITTABLE_STATUS = '待编制'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '待送审计划', value: 0 },
  { label: '待审批计划', value: 0 },
  { label: '已批复计划', value: 0 },
])

const selectedIds = ref<number[]>([])
const approver = ref('')
const submitting = ref(false)
const receipts = ref<Receipt[]>([])
const batchMessage = ref('')

const eligibleIds = computed(() =>
  rows.value.filter(isSubmittable).map((row) => Number(row.id)),
)
const allChecked = computed(
  () => eligibleIds.value.length > 0 && eligibleIds.value.every((id) => selectedIds.value.includes(id)),
)

function isSubmittable(row: Row) {
  return row.status === SUBMITTABLE_STATUS
}

function isSelected(row: Row) {
  return selectedIds.value.includes(Number(row.id))
}

function toggleRow(row: Row) {
  const id = Number(row.id)
  selectedIds.value = isSelected(row)
    ? selectedIds.value.filter((item) => item !== id)
    : [...selectedIds.value, id]
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : [...eligibleIds.value]
}

function displayCell(row: Row, column: string) {
  if (column === '计划状态') {
    return row.status ?? row[column] ?? '—'
  }
  return row[column] || '—'
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '点检计划登记入口尚未接入审批流'
}

async function submitBatch() {
  if (!selectedIds.value.length || submitting.value) {
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch-submit`, {
      method: 'POST',
      body: JSON.stringify({ ids: selectedIds.value, approver: approver.value.trim() || null }),
    })
    const payload = (await response.json()) as BatchResponse
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '批量送审未生效，请稍后重试')
    }
    receipts.value = payload.results ?? []
    batchMessage.value = payload.message
    selectedIds.value = []
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量送审失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('点检计划动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('点检计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    selectedIds.value = selectedIds.value.filter((id) => eligibleIds.value.includes(id))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划列表读取失败'
  }
}

async function reloadStats() {
  try {
    const payload = await fetchJson<Record<string, number>>(`${ENDPOINT}/stats`)
    stats.value = [
      { label: '待送审计划', value: payload['待编制'] ?? 0 },
      { label: '待审批计划', value: payload['待审批'] ?? 0 },
      { label: '已批复计划', value: payload['已批复'] ?? 0 },
    ]
  } catch {
    // 统计刷新失败不挡列表，下次操作会再拉一次
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
