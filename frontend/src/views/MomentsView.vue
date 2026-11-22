<script setup lang="ts">
/** 瞬间页：/trips/{id}/moments CRUD；坐标 WGS84 入库，media_json 存附件引用。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Camera, Plus, Trash2, Pencil, Loader2, MapPin } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import { formatDate } from '@/lib/utils'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Dialog from '@/components/ui/Dialog.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

interface Moment {
  id: string
  content: string | null
  mood: string | null
  lng: number | null
  lat: number | null
  coord_system: string
  taken_at: string | null
  media_json: string | null
}

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/moments`)
const items = ref<Moment[]>([])
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const deleteTarget = ref<Moment | null>(null)
const deleting = ref(false)

function emptyForm() {
  return { content: '', mood: '', lng: '', lat: '', taken_at: '', media_json: '' }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function toLocalInput(v: string | null): string { return v ? v.slice(0, 16) : '' }

async function load() {
  loading.value = true
  error.value = ''
  try { items.value = await api.get<Moment[]>(base.value) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogOpen.value = true
}
function openEdit(m: Moment) {
  editingId.value = m.id
  Object.assign(form, {
    content: m.content || '', mood: m.mood || '',
    lng: m.lng === null ? '' : String(m.lng), lat: m.lat === null ? '' : String(m.lat),
    taken_at: toLocalInput(m.taken_at), media_json: m.media_json || '',
  })
  dialogOpen.value = true
}

function num(v: string): number | null {
  if (v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
function body() {
  return {
    content: form.content || null, mood: form.mood || null,
    lng: num(form.lng), lat: num(form.lat), coord_system: 'WGS84',
    taken_at: form.taken_at || null, media_json: form.media_json || null,
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  error.value = ''
  try {
    if (editingId.value) await api.put(`${base.value}/${editingId.value}`, body())
    else await api.post(base.value, body())
    dialogOpen.value = false
    await load()
  } catch (e) { error.value = messageOf(e) } finally { saving.value = false }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  error.value = ''
  try { await api.del(`${base.value}/${deleteTarget.value.id}`); await load() } catch (e) { error.value = messageOf(e) } finally { deleting.value = false; deleteTarget.value = null }
}

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[900px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Camera class="h-5 w-5 text-primary" /> 旅途瞬间</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">随手记下路上的片段、心情与坐标</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记一条</Button>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!items.length" title="还没有瞬间" description="看到好看的风景，就写一句留在这里。" :icon="Camera">
        <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记第一条</Button>
      </EmptyState>
      <div v-else class="space-y-3">
        <div v-for="m in items" :key="m.id" class="rounded-lg border border-border bg-card p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <p class="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{{ m.content || '（无文字）' }}</p>
              <div class="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <span>{{ formatDate(m.taken_at) }}</span>
                <Badge v-if="m.mood" variant="outline">{{ m.mood }}</Badge>
                <span v-if="m.lng !== null && m.lat !== null" class="flex items-center gap-0.5">
                  <MapPin class="h-3 w-3" /> {{ m.lng.toFixed(4) }}, {{ m.lat.toFixed(4) }} · {{ m.coord_system }}
                </span>
              </div>
            </div>
            <div class="flex shrink-0 gap-0.5">
              <Button variant="ghost" size="sm" class="h-7 w-7 p-0" title="编辑" @click="openEdit(m)"><Pencil class="h-3.5 w-3.5" /></Button>
              <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive" title="删除" @click="deleteTarget = m"><Trash2 class="h-3.5 w-3.5" /></Button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <Dialog v-model="dialogOpen" :title="editingId ? '编辑瞬间' : '记一条瞬间'" width="max-w-lg">
      <div class="space-y-3">
        <div class="space-y-1"><label class="text-xs font-medium">内容</label>
          <textarea v-model="form.content" rows="3" class="w-full resize-none rounded-lg border border-input bg-card px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" placeholder="写点什么…" />
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div class="space-y-1"><label class="text-xs font-medium">心情标签</label><Input v-model="form.mood" placeholder="例如：晴朗" /></div>
          <div class="space-y-1"><label class="text-xs font-medium">时间</label><Input v-model="form.taken_at" type="datetime-local" /></div>
          <div class="space-y-1"><label class="text-xs font-medium">经度（WGS84）</label><Input v-model="form.lng" type="number" step="any" placeholder="可选" /></div>
          <div class="space-y-1"><label class="text-xs font-medium">纬度（WGS84）</label><Input v-model="form.lat" type="number" step="any" placeholder="可选" /></div>
          <div class="space-y-1 sm:col-span-2"><label class="text-xs font-medium">附件引用（media_json）</label><Input v-model="form.media_json" placeholder="可选，附件 ID 或 JSON 字符串" /></div>
        </div>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
      </template>
    </Dialog>

    <ConfirmDialog
      :model-value="!!deleteTarget"
      title="删除瞬间"
      message="删除后这条记录将不再显示，确定继续吗？"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteTarget = null }"
      @confirm="confirmDelete"
    />
  </div>
</template>
