<script setup lang="ts">
/** 物品页：/trips/{id}/packing/lists 两级（清单 + 条目），支持勾选已打包。 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Backpack, Plus, Trash2, Loader2, Check } from 'lucide-vue-next'
import { api, ApiError } from '@/lib/api'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Dialog from '@/components/ui/Dialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

interface PackingItem {
  id: string
  list_id: string
  name: string
  qty: number
  checked: boolean
  sort_key: string
}
interface PackingList {
  id: string
  name: string
  sort_key: string
  items: PackingItem[]
}

const route = useRoute()
const tripId = computed(() => String(route.params.tripId ?? ''))
const base = computed(() => `/trips/${encodeURIComponent(tripId.value)}/packing/lists`)
const lists = ref<PackingList[]>([])
const loading = ref(false)
const error = ref('')

const listDialog = ref(false)
const listName = ref('')
const savingList = ref(false)
const itemDialog = ref(false)
const itemTargetList = ref<PackingList | null>(null)
const itemName = ref('')
const itemQty = ref(1)
const savingItem = ref(false)
const deleteListTarget = ref<PackingList | null>(null)
const deleting = ref(false)

function messageOf(e: unknown): string {
  return e instanceof ApiError ? e.message : (e as Error)?.message || '操作失败'
}

async function load() {
  loading.value = true
  error.value = ''
  try { lists.value = await api.get<PackingList[]>(base.value) } catch (e) { error.value = messageOf(e) } finally { loading.value = false }
}

function openListDialog() { listName.value = ''; listDialog.value = true }
async function createList() {
  if (!listName.value.trim() || savingList.value) return
  savingList.value = true
  error.value = ''
  try {
    const created = await api.post<PackingList>(base.value, { name: listName.value.trim() })
    lists.value.push({ ...created, items: created.items ?? [] })
    listDialog.value = false
  } catch (e) { error.value = messageOf(e) } finally { savingList.value = false }
}

function openItemDialog(list: PackingList) {
  itemTargetList.value = list
  itemName.value = ''
  itemQty.value = 1
  itemDialog.value = true
}
async function createItem() {
  const list = itemTargetList.value
  if (!list || !itemName.value.trim() || savingItem.value) return
  savingItem.value = true
  error.value = ''
  try {
    const created = await api.post<PackingItem>(`${base.value}/${list.id}/items`, {
      name: itemName.value.trim(), qty: Number(itemQty.value) || 1, checked: false,
    })
    list.items = [...(list.items ?? []), created]
    itemDialog.value = false
  } catch (e) { error.value = messageOf(e) } finally { savingItem.value = false }
}

/** 勾选：PUT 单条 item，失败回滚本地状态。 */
async function toggleItem(list: PackingList, item: PackingItem) {
  const before = item.checked
  item.checked = !before
  try {
    await api.put(`${base.value}/${list.id}/items/${item.id}`, { checked: item.checked })
  } catch (e) {
    item.checked = before
    error.value = messageOf(e)
  }
}

async function removeItem(list: PackingList, item: PackingItem) {
  try {
    await api.del(`${base.value}/${list.id}/items/${item.id}`)
    list.items = (list.items ?? []).filter((i) => i.id !== item.id)
  } catch (e) { error.value = messageOf(e) }
}

async function confirmDeleteList() {
  if (!deleteListTarget.value) return
  deleting.value = true
  error.value = ''
  try {
    await api.del(`${base.value}/${deleteListTarget.value.id}`)
    lists.value = lists.value.filter((l) => l.id !== deleteListTarget.value?.id)
  } catch (e) { error.value = messageOf(e) } finally { deleting.value = false; deleteListTarget.value = null }
}

const totalItems = computed(() => lists.value.reduce((n, l) => n + (l.items?.length ?? 0), 0))
const checkedItems = computed(() => lists.value.reduce((n, l) => n + (l.items ?? []).filter((i) => i.checked).length, 0))

onMounted(load)
</script>

<template>
  <div class="mx-auto max-w-[1100px] space-y-5 px-5 py-6">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h1 class="flex items-center gap-2 text-lg font-semibold"><Backpack class="h-5 w-5 text-primary" /> 物品清单</h1>
        <p class="mt-0.5 text-xs text-muted-foreground">
          共 {{ lists.length }} 个清单 · {{ checkedItems }} / {{ totalItems }} 已打包
        </p>
      </div>
      <Button size="sm" @click="openListDialog"><Plus class="h-3.5 w-3.5" /> 新建清单</Button>
    </div>

    <p v-if="error" class="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">{{ error }}</p>
    <div v-if="loading" class="py-10 text-center text-sm text-muted-foreground"><Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载中…</div>

    <template v-else>
      <EmptyState v-if="!lists.length" title="还没有物品清单" description="按「证件 / 衣物 / 电子设备」分组准备。" :icon="Backpack">
        <Button size="sm" @click="openListDialog"><Plus class="h-3.5 w-3.5" /> 新建清单</Button>
      </EmptyState>
      <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card v-for="list in lists" :key="list.id">
          <div class="mb-3 flex items-center justify-between gap-2">
            <h2 class="truncate text-sm font-semibold text-foreground">{{ list.name }}</h2>
            <div class="flex shrink-0 gap-0.5">
              <Button variant="ghost" size="sm" class="h-7 w-7 p-0 text-muted-foreground hover:text-destructive" title="删除清单" @click="deleteListTarget = list">
                <Trash2 class="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
          <div class="space-y-1">
            <div v-for="item in list.items ?? []" :key="item.id" class="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-muted">
              <input
                type="checkbox"
                class="h-3.5 w-3.5 shrink-0 accent-[var(--primary)]"
                :checked="item.checked"
                @change="toggleItem(list, item)"
              />
              <span class="min-w-0 flex-1 truncate text-xs" :class="item.checked ? 'text-muted-foreground line-through' : 'text-foreground'">
                {{ item.name }}
              </span>
              <span class="shrink-0 text-[10px] text-muted-foreground">×{{ item.qty }}</span>
              <button class="shrink-0 text-muted-foreground hover:text-destructive" title="删除条目" @click="removeItem(list, item)">
                <Trash2 class="h-3 w-3" />
              </button>
            </div>
            <p v-if="!(list.items ?? []).length" class="py-2 text-center text-[11px] text-muted-foreground">清单还是空的</p>
          </div>
          <Button variant="outline" size="sm" class="mt-3 w-full" @click="openItemDialog(list)">
            <Plus class="h-3.5 w-3.5" /> 添加物品
          </Button>
        </Card>
      </div>
    </template>

    <Dialog v-model="listDialog" title="新建清单" width="max-w-sm">
      <div class="space-y-1.5">
        <label class="text-xs font-medium">清单名称</label>
        <Input v-model="listName" placeholder="例如：证件与贵重物品" />
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="savingList" @click="listDialog = false">取消</Button>
        <Button size="sm" :disabled="savingList || !listName.trim()" @click="createList">
          <Loader2 v-if="savingList" class="h-3.5 w-3.5 animate-spin" /> 创建
        </Button>
      </template>
    </Dialog>

    <Dialog v-model="itemDialog" title="添加物品" width="max-w-sm">
      <div class="grid grid-cols-[1fr_80px] items-end gap-2">
        <div class="space-y-1.5"><label class="text-xs font-medium">名称</label><Input v-model="itemName" placeholder="例如：充电宝" /></div>
        <div class="space-y-1.5"><label class="text-xs font-medium">数量</label><Input v-model="itemQty" type="number" min="1" /></div>
      </div>
      <template #footer>
        <Button variant="outline" size="sm" :disabled="savingItem" @click="itemDialog = false">取消</Button>
        <Button size="sm" :disabled="savingItem || !itemName.trim()" @click="createItem">
          <Loader2 v-if="savingItem" class="h-3.5 w-3.5 animate-spin" /><Check v-else class="h-3.5 w-3.5" /> 添加
        </Button>
      </template>
    </Dialog>

    <ConfirmDialog
      :model-value="!!deleteListTarget"
      title="删除清单"
      message="清单下的所有物品也会一并删除，确定继续吗？"
      danger
      :busy="deleting"
      @update:model-value="(v) => { if (!v) deleteListTarget = null }"
      @confirm="confirmDeleteList"
    />
  </div>
</template>
