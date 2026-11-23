<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Users, Plus, Save, Trash2, Loader2, X } from 'lucide-vue-next'
import { api } from '@/lib/api'
import { useToastStore } from '@/stores/toast'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
interface Member { id: string; name: string; is_child: boolean; note: string }
interface Household { id: string; name: string; note: string; members: Member[] }
interface Traveler { id: string; name: string; note: string }
const toast = useToastStore()
const households = ref<Household[]>([])
const travelers = ref<Traveler[]>([])
const loading = ref(true)
const ready = ref(false)
const busy = ref(false)
const newTraveler = ref({ name: '', note: '' })
const newHousehold = ref({ name: '', note: '' })
const addingMember = ref<Record<string, { name: string; is_child: boolean; note: string }>>({})
const editTraveler = ref<string | null>(null)
const editHousehold = ref<string | null>(null)
const editMember = ref<string | null>(null)
async function load() {
  loading.value = true
  try {
    const [familyRows, peopleRows] = await Promise.all([
      api.get<Household[]>('/households'),
      api.get<Traveler[]>('/frequent-travelers'),
    ])
    households.value = familyRows.map((family) => ({ ...family, note: family.note || '', members: family.members.map((member) => ({ ...member, note: member.note || '' })) }))
    travelers.value = peopleRows.map((person) => ({ ...person, note: person.note || '' }))
    for (const family of familyRows) addingMember.value[family.id] ??= { name: '', is_child: false, note: '' }
    ready.value = true
  } catch (e) { toast.error(e instanceof Error ? e.message : '家庭与人员读取失败') }
  finally { loading.value = false }
}
async function action(fn: () => Promise<unknown>, success: string) {
  if (busy.value) return false
  busy.value = true
  try { await fn(); toast.success(success); await load(); return true }
  catch (e) { toast.error(e instanceof Error ? e.message : '操作失败'); return false }
  finally { busy.value = false }
}
async function addTraveler() {
  if (!newTraveler.value.name.trim()) return
  if (await action(() => api.post('/frequent-travelers', { name: newTraveler.value.name.trim(), note: newTraveler.value.note || null }), '常用人员已添加'))
    newTraveler.value = { name: '', note: '' }
}
async function saveTraveler(person: Traveler) {
  if (await action(() => api.put(`/frequent-travelers/${encodeURIComponent(person.id)}`, { name: person.name, note: person.note }), '常用人员已保存'))
    editTraveler.value = null
}
async function deleteTraveler(person: Traveler) {
  if (!window.confirm(`确定删除常用人员“${person.name}”吗？`)) return
  await action(() => api.del(`/frequent-travelers/${encodeURIComponent(person.id)}`), '常用人员已删除')
}
async function addHousehold() {
  if (!newHousehold.value.name.trim()) return
  if (await action(() => api.post('/households', { name: newHousehold.value.name.trim(), note: newHousehold.value.note || null }), '家庭已创建'))
    newHousehold.value = { name: '', note: '' }
}
async function saveHousehold(family: Household) {
  if (await action(() => api.put(`/households/${encodeURIComponent(family.id)}`, { name: family.name, note: family.note }), '家庭已保存'))
    editHousehold.value = null
}
async function deleteHousehold(family: Household) {
  if (!window.confirm(`确定删除家庭“${family.name}”及其成员吗？`)) return
  await action(() => api.del(`/households/${encodeURIComponent(family.id)}`), '家庭已删除')
}
async function addMember(family: Household) {
  const form = addingMember.value[family.id]
  if (!form?.name.trim()) return
  if (await action(() => api.post(`/households/${encodeURIComponent(family.id)}/members`, { name: form.name.trim(), is_child: form.is_child, note: form.note || null }), '家庭成员已添加'))
    addingMember.value[family.id] = { name: '', is_child: false, note: '' }
}
async function saveMember(family: Household, member: Member) {
  if (await action(() => api.put(`/households/${encodeURIComponent(family.id)}/members/${encodeURIComponent(member.id)}`, { name: member.name, is_child: member.is_child, note: member.note }), '家庭成员已保存'))
    editMember.value = null
}
async function deleteMember(family: Household, member: Member) {
  if (!window.confirm(`确定移除成员“${member.name}”吗？`)) return
  await action(() => api.del(`/households/${encodeURIComponent(family.id)}/members/${encodeURIComponent(member.id)}`), '家庭成员已移除')
}
onMounted(load)
</script>
<template>
  <div class="space-y-4">
    <Card class="space-y-3"><div><h2 class="flex items-center gap-2 text-sm font-semibold"><Users class="h-4 w-4 text-primary" /> 家庭与常用人员</h2><p class="mt-1 text-xs text-muted-foreground">管理家庭成员和个人常用人员，可在行程中快速添加。</p></div>
      <p v-if="loading" class="text-xs text-muted-foreground">正在读取…</p>
      <Button v-else-if="!ready" variant="outline" size="sm" @click="load">重新读取</Button>
      <template v-else>
        <form class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]" @submit.prevent="addTraveler"><Input v-model="newTraveler.name" placeholder="常用人员姓名" /><Input v-model="newTraveler.note" placeholder="备注（可选）" /><Button size="sm" type="submit" :disabled="busy || !newTraveler.name.trim()"><Plus class="h-3.5 w-3.5" /> 添加人员</Button></form>
        <div v-for="person in travelers" :key="person.id" class="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-[1fr_1fr_auto]"><Input v-model="person.name" :disabled="editTraveler !== person.id || busy" aria-label="常用人员姓名" /><Input v-model="person.note" :disabled="editTraveler !== person.id || busy" aria-label="常用人员备注" /><div class="flex gap-1"><Button v-if="editTraveler !== person.id" variant="outline" size="sm" :disabled="busy" @click="editTraveler = person.id">编辑</Button><Button v-else size="sm" :disabled="busy" @click="saveTraveler(person)"><Save class="h-3 w-3" /> 保存</Button><Button variant="ghost" size="sm" :disabled="busy" aria-label="删除人员" @click="deleteTraveler(person)"><Trash2 class="h-3.5 w-3.5" /></Button></div></div>
        <p v-if="!travelers.length" class="text-xs text-muted-foreground">暂无常用人员。</p>
        <div class="border-t border-border pt-3"><h3 class="mb-2 text-xs font-semibold">家庭</h3><form class="mb-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]" @submit.prevent="addHousehold"><Input v-model="newHousehold.name" placeholder="家庭名称" /><Input v-model="newHousehold.note" placeholder="备注（可选）" /><Button size="sm" type="submit" :disabled="busy || !newHousehold.name.trim()"><Plus class="h-3.5 w-3.5" /> 创建家庭</Button></form>
          <div v-for="family in households" :key="family.id" class="mb-3 space-y-2 rounded-lg border border-border p-3"><div class="grid gap-2 sm:grid-cols-[1fr_1fr_auto]"><Input v-model="family.name" :disabled="editHousehold !== family.id || busy" aria-label="家庭名称" /><Input v-model="family.note" :disabled="editHousehold !== family.id || busy" aria-label="家庭备注" /><div class="flex gap-1"><Button v-if="editHousehold !== family.id" variant="outline" size="sm" :disabled="busy" @click="editHousehold = family.id">编辑</Button><Button v-else size="sm" :disabled="busy" @click="saveHousehold(family)"><Save class="h-3 w-3" /> 保存</Button><Button variant="ghost" size="sm" :disabled="busy" aria-label="删除家庭" @click="deleteHousehold(family)"><Trash2 class="h-3.5 w-3.5" /></Button></div></div>
            <div v-for="member in family.members" :key="member.id" class="grid gap-2 rounded-md bg-muted/40 p-2 sm:grid-cols-[1fr_1fr_auto_auto]"><Input v-model="member.name" :disabled="editMember !== member.id || busy" aria-label="成员姓名" /><Input v-model="member.note" :disabled="editMember !== member.id || busy" aria-label="成员备注" /><label class="flex items-center gap-1 text-xs"><input v-model="member.is_child" type="checkbox" :disabled="editMember !== member.id || busy" /> 儿童</label><div class="flex gap-1"><Button v-if="editMember !== member.id" variant="outline" size="sm" :disabled="busy" @click="editMember = member.id">编辑</Button><Button v-else size="sm" :disabled="busy" @click="saveMember(family, member)"><Save class="h-3 w-3" /> 保存</Button><Button variant="ghost" size="sm" :disabled="busy" aria-label="删除成员" @click="deleteMember(family, member)"><X class="h-3.5 w-3.5" /></Button></div></div>
            <form class="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]" @submit.prevent="addMember(family)"><Input v-model="addingMember[family.id].name" placeholder="成员姓名" /><Input v-model="addingMember[family.id].note" placeholder="备注（可选）" /><label class="flex items-center gap-1 text-xs"><input v-model="addingMember[family.id].is_child" type="checkbox" /> 儿童</label><Button size="sm" type="submit" :disabled="busy || !addingMember[family.id].name.trim()"><Plus class="h-3.5 w-3.5" /> 添加成员</Button></form>
          </div><p v-if="!households.length" class="text-xs text-muted-foreground">暂无家庭。</p>
        </div>
      </template>
    </Card>
  </div>
</template>
