<template>
  <section class="page" data-module="accident">
    <header class="page-head">
      <div>
        <h2>事故记录管理</h2>
        <p class="page-desc">维护事故记录，围绕事故编号、关联任务、事故类型、发生时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记事故记录</button>
        <button class="btn" type="button" @click="exportRows">导出事故记录清单</button>
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

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无事故记录数据，可先登记事故记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条事故记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/accident'
const columns = ["事故编号", "关联任务", "事故类型", "发生时间", "事故描述", "损失金额", "保险理赔", "事故状态"]
const actions = ["上报事故", "损失核定", "启动理赔", "理赔到账"]
const statuses = ["待上报", "已上报", "待理赔", "理赔中", "已理赔"]
const stats = [{"label": "待上报事故", "value": 0}, {"label": "待理赔事故", "value": 0}, {"label": "已理赔事故", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '事故记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  // 后端动作接口的入参统一包在 values 里；核损与理赔到账自动带上金额与结论，
  // 这样页面按钮也能把「上报 -> 核损 -> 理赔」整条链路点通。
  const values: Record<string, string | number> = { action }
  if (action === '损失核定' && row['损失金额'] != null && row['损失金额'] !== '') {
    values['损失金额'] = row['损失金额']
  }
  if (action === '理赔到账') {
    const loss = Number(row['损失金额'])
    if (Number.isFinite(loss) && loss > 0) {
      values['损失金额'] = loss
      values['赔付金额'] = Math.round(loss * 0.8 * 100) / 100
    }
    values['理赔结论'] = '保险已赔付'
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    if (!response.ok) {
      throw new Error('事故记录动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (payload.ok === false) {
      throw new Error(payload.message || '事故记录动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '事故记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('事故记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '事故记录列表读取失败'
  }
}

onMounted(reload)
</script>
