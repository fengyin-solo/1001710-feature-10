<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>点检计划管理</h2>
        <p class="page-desc">在待编制的计划上勾选标记，把选中的计划一次批量送审；点检周期或计划工期没填全的会被挑出，逐张回执成功或失败。</p>
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
      <label class="batch-selector">
        <input
          type="checkbox"
          :checked="allCurrentSelected"
          :indeterminate.prop="someCurrentSelected && !allCurrentSelected"
          @change="toggleSelectAll"
        />
        <span>全选本页待编制</span>
      </label>
      <label class="batch-approver">
        <span>审批人</span>
        <input v-model="approver" placeholder="可选，默认使用计划上的审批人员" />
      </label>
      <button
        class="btn primary"
        type="button"
        :disabled="submitting || selectedIds.size === 0"
        @click="batchSubmit"
      >
        {{ submitting ? '送审中…' : `批量送审（已选 ${selectedIds.size} 张）` }}
      </button>
      <button
        v-if="selectedIds.size"
        class="btn ghost"
        type="button"
        :disabled="submitting"
        @click="clearSelection"
      >
        清空标记
      </button>
      <span class="batch-hint">可勾选所有待编制计划；缺点检周期或计划工期的会在回执里被挑出、不跟着送审。</span>
    </div>

    <div v-if="receipt" class="receipt-panel" :class="receipt.summary.submitted > 0 ? 'has-success' : 'all-failed'">
      <header class="receipt-head">
        <strong>{{ receipt.message }}</strong>
        <button class="link" type="button" @click="receipt = null">关闭回执</button>
      </header>
      <ul class="receipt-list">
        <li v-for="(item, index) in receipt.items" :key="`${item.id}-${index}`" class="receipt-item">
          <span class="receipt-tag" :class="receiptClass(item.code)">{{ receiptLabel(item.code) }}</span>
          <span class="receipt-no">{{ item['计划编号'] || `#${item.id}` }}</span>
          <span class="receipt-msg" :class="{ 'error-text': !item.ok }">{{ item.message }}</span>
        </li>
      </ul>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th class="col-check">标记</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>审批状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-selected': selectedIds.has(Number(row.id)) }">
          <td class="col-check">
            <input
              v-if="canSubmit(row)"
              type="checkbox"
              :checked="selectedIds.has(Number(row.id))"
              @change="toggleOne(row)"
            />
            <span v-else class="check-disabled" title="仅待编制的计划可以勾选送审">—</span>
          </td>
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td><span class="status-tag" :class="statusClass(row.status)">{{ row.status }}</span></td>
          <td class="row-actions">
            <button
              v-if="row.status === '待编制'"
              class="link"
              type="button"
              @click="runAction('提交审批', row)"
            >
              提交审批
            </button>
            <button
              v-if="row.status === '待审批'"
              class="link"
              type="button"
              @click="runAction('确认批复', row)"
            >
              确认批复
            </button>
            <button
              v-if="row.status === '待编制' || row.status === '待审批'"
              class="link danger"
              type="button"
              @click="runAction('作废计划', row)"
            >
              作废计划
            </button>
            <span v-if="row.status === '已批复' || row.status === '已作废'" class="action-muted">无可用动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无点检计划数据，可先登记点检计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条点检计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type StatusCounts = Record<string, number>

type ReceiptItem = {
  id: number
  计划编号: string | null
  ok: boolean
  code: string
  message: string
}
type BatchReceipt = {
  ok: boolean
  message: string
  summary: Record<string, number>
  items: ReceiptItem[]
}

const ENDPOINT = '/api/plan'
const columns = ["计划编号", "点检对象", "点检周期", "点检项目", "计划工期", "编制人员", "审批人员"]
const statuses = ["待编制", "待审批", "已批复", "已作废"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = ["计划编号", "点检对象", "点检周期"]

const selectedIds = ref<Set<number>>(new Set())
const approver = ref('')
const submitting = ref(false)
const receipt = ref<BatchReceipt | null>(null)
const statusCounts = ref<StatusCounts>({})

const stats = computed(() => [
  { label: "待编制计划", value: countByStatus('待编制') },
  { label: "待审批计划", value: countByStatus('待审批') },
  { label: "已批复计划", value: countByStatus('已批复') },
  { label: "已作废计划", value: countByStatus('已作废') },
])

const submittableRows = computed(() => rows.value.filter(canSubmit))
const allCurrentSelected = computed(
  () => submittableRows.value.length > 0
    && submittableRows.value.every((row) => selectedIds.value.has(Number(row.id))),
)
const someCurrentSelected = computed(
  () => submittableRows.value.some((row) => selectedIds.value.has(Number(row.id))),
)

function countByStatus(status: string): number {
  return statusCounts.value[status] ?? 0
}

function canSubmit(row: Row): boolean {
  return row.status === '待编制'
}

function toggleOne(row: Row) {
  const id = Number(row.id)
  const next = new Set(selectedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  selectedIds.value = next
}

function toggleSelectAll(event: Event) {
  const checked = (event.target as HTMLInputElement).checked
  const next = new Set(selectedIds.value)
  for (const row of submittableRows.value) {
    const id = Number(row.id)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
  }
  selectedIds.value = next
}

function clearSelection() {
  selectedIds.value = new Set()
}

function statusClass(status: Row['status']): string {
  return {
    '待编制': 'status-draft',
    '待审批': 'status-pending',
    '已批复': 'status-approved',
    '已作废': 'status-void',
  }[String(status)] ?? 'status-draft'
}

function receiptLabel(code: string): string {
  return {
    submitted: '成功',
    incomplete: '资料不全',
    conflict: '已被处理',
    not_found: '查无此单',
    duplicate: '重复',
  }[code] ?? '未处理'
}

function receiptClass(code: string): string {
  return code === 'submitted' ? 'receipt-ok' : 'receipt-fail'
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

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '点检计划动作未生效，请稍后重试')
    }
    const nextSelected = new Set(selectedIds.value)
    nextSelected.delete(Number(row.id))
    selectedIds.value = nextSelected
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划操作失败'
  }
}

async function batchSubmit() {
  if (!selectedIds.value.size || submitting.value) {
    return
  }
  errorMessage.value = ''
  receipt.value = null
  submitting.value = true
  try {
    const ids = [...selectedIds.value]
    const response = await request(`${ENDPOINT}/batch-submit`, {
      method: 'POST',
      body: JSON.stringify({ ids, approver: approver.value || null }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new Error(payload?.detail ?? '批量送审未送达，请稍后重试')
    }
    receipt.value = payload as BatchReceipt
    clearSelection()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量送审失败'
  } finally {
    submitting.value = false
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    statusCounts.value = (await response.json()) as StatusCounts
  } catch {
    // 统计加载失败不阻塞列表，卡片保持上一次结果
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
    // 勾选范围跟随当前列表：翻页或筛选后，不在本页的勾选自动失效
    const visibleIds = new Set(rows.value.map((row: Row) => Number(row.id)))
    selectedIds.value = new Set(
      [...selectedIds.value].filter((id) => visibleIds.has(id)),
    )
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划列表读取失败'
  }
}

onMounted(reload)
</script>
