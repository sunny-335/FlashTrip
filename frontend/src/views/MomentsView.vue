<script setup lang="ts">
/** 瞬间页：/trips/{id}/moments CRUD；坐标按全球通用坐标系入库。
 *  - 图片通过 POST /uploads 上传，附件 ID 以 JSON 数组字符串存入 media_json；
 *  - 列表渲染缩略图网格，点击放大；
 *  - 每条瞬间可单独设置「对外展示」（is_public），默认值取自全局设置 moment_default_public；
 *  - 可见范围由后端按发布者设置过滤，本页只展示接口返回的数据，不在前端硬拦权限。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Camera, Plus, Trash2, Pencil, Loader2, MapPin, ImageUp, X, Eye } from 'lucide-vue-next'
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
  is_public: boolean
}
/** 上传接口返回的附件，只用到 id。 */
interface Attachment { id: string; filename: string }

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/moments`)
const items = ref<Moment[]>([])
const loading = ref(false)
const error = ref('')
const dialogOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const uploading = ref(false)
const formError = ref('')
const deleteTarget = ref<Moment | null>(null)
const deleting = ref(false)
/** 新建瞬间的默认对外展示值，来自 GET /settings 的 moment_default_public。 */
const defaultPublic = ref(false)
/** 图片放大查看地址。 */
const previewUrl = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function emptyForm() {
  return {
    content: '', mood: '', lng: '', lat: '', taken_at: '',
    mediaIds: [] as string[], is_public: false,
  }
}
const form = reactive(emptyForm())

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}
function toLocalInput(v: string | null): string { return v ? v.slice(0, 16) : '' }

/** 附件直接由后端 GET /uploads/{id} 返回文件，可作为 <img> 地址。 */
function mediaUrl(id: string): string {
  return `/api/v1/uploads/${encodeURIComponent(id)}`
}

/** media_json 为附件 ID 的 JSON 数组字符串；兼容旧的手填单值。 */
function parseMedia(raw: string | null): string[] {
  if (!raw) return []
  const s = raw.trim()
  if (!s) return []
  try {
    const v: unknown = JSON.parse(s)
    if (Array.isArray(v)) return v.filter((x): x is string => typeof x === 'string' && Boolean(x))
    if (typeof v === 'string' && v) return [v]
  } catch {
    if (!s.startsWith('[') && !s.startsWith('{')) return [s]
  }
  return []
}

async function load() {
  loading.value = true
  error.value = ''
  try { items.value = await api.get<Moment[]>(base.value) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

async function loadDefaultPublic() {
  try {
    const s = await api.get<{ moment_default_public?: boolean }>('/settings')
    defaultPublic.value = Boolean(s.moment_default_public)
  } catch {
    defaultPublic.value = false // 读取失败时按默认私有处理
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  form.is_public = defaultPublic.value
  formError.value = ''
  dialogOpen.value = true
}
function openEdit(m: Moment) {
  editingId.value = m.id
  Object.assign(form, {
    content: m.content || '', mood: m.mood || '',
    lng: m.lng === null ? '' : String(m.lng), lat: m.lat === null ? '' : String(m.lat),
    taken_at: toLocalInput(m.taken_at), mediaIds: parseMedia(m.media_json),
    is_public: Boolean(m.is_public),
  })
  formError.value = ''
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
    taken_at: form.taken_at || null,
    media_json: form.mediaIds.length ? JSON.stringify(form.mediaIds) : null,
    is_public: form.is_public,
  }
}

async function save() {
  if (saving.value || uploading.value) return
  saving.value = true
  formError.value = ''
  try {
    if (editingId.value) await api.put(`${base.value}/${editingId.value}`, body())
    else await api.post(base.value, body())
    dialogOpen.value = false
    await load()
  } catch (e) { formError.value = messageOf(e) } finally { saving.value = false }
}

/** 选择多张图片后逐个上传：每次只带 file / trip_id / kind 三个字段，文件夹由后端自动创建。 */
async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  if (!files.length) return
  uploading.value = true
  formError.value = ''
  try {
    for (const file of files) {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('trip_id', tripId.value)
      fd.append('kind', 'moment')
      const att = await api.upload<Attachment>('/uploads', fd)
      if (att?.id && !form.mediaIds.includes(att.id)) form.mediaIds.push(att.id)
    }
  } catch (err) {
    formError.value = messageOf(err)
  } finally {
    uploading.value = false
    input.value = '' // 允许重复选择同一文件
  }
}

function removeMedia(id: string) {
  form.mediaIds = form.mediaIds.filter((x) => x !== id)
}

/** 列表内直接切换单条对外展示状态，只提交 is_public，错误交给后端中文提示。 */
async function togglePublic(m: Moment) {
  const next = !m.is_public
  try {
    await api.put(`${base.value}/${m.id}`, { is_public: next })
    m.is_public = next
  } catch (e) { error.value = messageOf(e) }
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  error.value = ''
  try { await api.del(`${base.value}/${deleteTarget.value.id}`); await load() } catch (e) { error.value = messageOf(e) } finally { deleting.value = false; deleteTarget.value = null }
}

onMounted(() => { void Promise.all([load(), loadDefaultPublic()]) })
</script>

<template>
  <div class="mx-auto max-w-[900px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Camera class="h-5 w-5 text-primary" /> 旅途瞬间</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">随手记下路上的片段、心情、照片与坐标</p>
      </div>
      <Button size="sm" @click="openCreate"><Plus class="h-3.5 w-3.5" /> 记一条</Button>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!items.length" title="还没有瞬间" description="看到好看的风景，就写一句、传张照片留在这里。" :icon="Camera">
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
                <Badge :variant="m.is_public ? 'default' : 'secondary'">
                  <Eye class="mr-0.5 inline h-2.5 w-2.5" />{{ m.is_public ? '对外展示' : '仅自己可见' }}
                </Badge>
                <span v-if="m.lng !== null && m.lat !== null" class="flex items-center gap-0.5">
                  <MapPin class="h-3 w-3" /> {{ m.lng.toFixed(4) }}, {{ m.lat.toFixed(4) }} · {{ m.coord_system }} 坐标系
                </span>
              </div>
            </div>
            <div class="flex shrink-0 flex-wrap justify-end gap-1.5">
              <Button variant="outline" size="sm" @click="openEdit(m)"><Pencil class="h-3.5 w-3.5" /> 编辑</Button>
              <Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10 hover:text-destructive" @click="deleteTarget = m"><Trash2 class="h-3.5 w-3.5" /> 删除</Button>
            </div>
          </div>

          <!-- 图片缩略图网格，点击放大 -->
          <div v-if="parseMedia(m.media_json).length" class="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
            <button
              v-for="id in parseMedia(m.media_json)"
              :key="id"
              class="aspect-square overflow-hidden rounded-md border border-border bg-muted"
              @click="previewUrl = mediaUrl(id)"
            >
              <img :src="mediaUrl(id)" alt="瞬间图片" class="h-full w-full object-cover" />
            </button>
          </div>

          <!-- 逐条对外展示开关 -->
          <div class="mt-3 border-t border-border pt-2.5">
            <label class="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs text-foreground">
              <input
                type="checkbox"
                class="h-4 w-4 accent-[var(--primary)]"
                :checked="m.is_public"
                @change="togglePublic(m)"
              />
              对外展示
              <span class="text-[11px] text-muted-foreground">开启后，协作者与分享链接可见这条瞬间</span>
            </label>
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
          <div class="space-y-1"><label class="text-xs font-medium">经度</label><Input v-model="form.lng" type="number" step="any" placeholder="全球通用坐标系经度" /></div>
          <div class="space-y-1"><label class="text-xs font-medium">纬度</label><Input v-model="form.lat" type="number" step="any" placeholder="全球通用坐标系纬度" /></div>
        </div>

        <!-- 图片管理与上传 -->
        <div class="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
          <div class="flex items-center justify-between gap-2">
            <label class="flex items-center gap-1.5 text-xs font-medium"><ImageUp class="h-3.5 w-3.5 text-primary" /> 图片</label>
            <Button variant="outline" size="sm" :disabled="uploading" @click="fileInput?.click()">
              <Loader2 v-if="uploading" class="h-3.5 w-3.5 animate-spin" />
              <Plus v-else class="h-3.5 w-3.5" />
              {{ uploading ? '上传中…' : '添加图片' }}
            </Button>
            <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="onFiles" />
          </div>
          <div v-if="form.mediaIds.length" class="grid grid-cols-3 gap-2 sm:grid-cols-4">
            <div v-for="id in form.mediaIds" :key="id" class="group relative aspect-square overflow-hidden rounded-md border border-border bg-muted">
              <img :src="mediaUrl(id)" alt="待保存图片" class="h-full w-full object-cover" />
              <button
                class="absolute right-1 top-1 rounded-md border border-white/40 bg-black/50 p-1 text-white"
                aria-label="移除图片"
                @click="removeMedia(id)"
              ><X class="h-3 w-3" /></button>
            </div>
          </div>
          <p v-else class="text-[11px] text-muted-foreground">仅支持图片，单张不超过 20MB；保存前的图片会先上传到服务器。</p>
        </div>

        <!-- 可见性开关 -->
        <label class="flex min-h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-xs text-foreground">
          <input v-model="form.is_public" type="checkbox" class="h-4 w-4 accent-[var(--primary)]" />
          对外展示
          <span class="text-[11px] text-muted-foreground">默认跟随全局设置，可逐条单独调整</span>
        </label>

        <p v-if="formError" class="rounded-md border border-destructive/40 bg-destructive/5 px-2.5 py-2 text-xs text-destructive">{{ formError }}</p>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="saving || uploading" @click="dialogOpen = false">取消</Button>
        <Button size="sm" :disabled="saving || uploading" @click="save"><Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" /> 保存</Button>
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

    <!-- 图片放大查看：点击遮罩关闭 -->
    <div v-if="previewUrl" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" @click="previewUrl = ''">
      <img :src="previewUrl" alt="瞬间图片大图" class="max-h-full max-w-full rounded-lg object-contain shadow-lg" @click.stop />
      <button class="absolute right-5 top-5 rounded-lg border border-white/40 bg-black/40 p-2 text-white" aria-label="关闭" @click="previewUrl = ''">
        <X class="h-5 w-5" />
      </button>
    </div>
  </div>
</template>
