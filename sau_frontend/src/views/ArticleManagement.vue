<template>
  <div class="article-workspace">
    <header class="workspace-header">
      <div>
        <p class="workspace-kicker">内容发布 / 文章</p>
        <h1>文章工作台</h1>
        <p class="workspace-description">准备一份图文，分别发布到所选平台；支持文章和图文笔记。</p>
      </div>
      <el-button @click="createDraft"><el-icon><Plus /></el-icon>新建文章</el-button>
    </header>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error" />
    <div class="workspace-grid" v-loading="initialLoading || saving">
      <aside class="draft-rail">
        <div class="rail-heading"><span>我的文章</span><span>{{ articles.length }}</span></div>
        <el-input v-model="search" placeholder="搜索标题" clearable aria-label="搜索文章标题" />
        <div class="draft-list">
          <button v-for="article in filteredArticles" :key="article.id" type="button"
            :class="['draft-row', { selected: article.id === form.id }]" @click="openArticle(article.id)">
            <span class="draft-title">{{ article.title || '未命名文章' }}</span>
            <span class="draft-meta">修订 {{ article.revision }} · {{ formatTime(article.updated_at) }}</span>
          </button>
          <p v-if="!filteredArticles.length" class="empty-note">{{ search ? '没有匹配的文章' : '保存后的文章会显示在这里' }}</p>
        </div>
      </aside>

      <section class="writing-panel">
        <div class="writing-topbar">
          <div class="save-state"><span :class="['state-dot', { dirty }]" />{{ dirty ? '有未保存修改' : form.id ? `已保存 · 修订 ${form.revision}` : '新文章' }}</div>
          <div class="writing-actions">
            <el-button text @click="importVisible = true">导入内容</el-button>
            <el-button :loading="saving" :disabled="!dirty && !!form.id" @click="saveArticle()">保存文章</el-button>
          </div>
        </div>
        <el-alert v-if="revisionConflict" type="warning" :closable="false" show-icon
          title="文章已在其他入口修改。当前编辑内容仍保留，请复制需要保留的内容，再重新载入最新修订。">
          <el-button text @click="reloadArticle">重新载入最新修订</el-button>
        </el-alert>
        <div class="document-cover">
          <div class="cover-thumbnail" v-if="form.cover_asset_id">
            <img :src="assetUrl(form.cover_asset_id)" alt="文章默认封面" />
            <el-button circle size="small" aria-label="移除封面" @click="removeCover"><el-icon><Close /></el-icon></el-button>
          </div>
          <button type="button" class="cover-upload" :disabled="uploading" @click="coverInput.click()">
            <el-icon><Picture /></el-icon>{{ form.cover_asset_id ? '更换默认封面' : '添加默认封面' }}
          </button>
          <span>可在各平台设置中单独覆盖</span>
          <input ref="coverInput" type="file" hidden accept="image/jpeg,image/png,image/webp" @change="uploadCover" />
        </div>
        <el-input v-model="form.title" class="document-title" placeholder="输入文章标题" aria-label="文章标题" @input="markDirty" />
        <div class="editor-toolbar" role="toolbar" aria-label="文章格式工具">
          <button v-for="item in formatTools" :key="item.label" type="button" :title="item.label" :aria-label="item.label"
            :class="{ active: editor?.isActive(item.active, item.attrs) }" @click="item.run()">{{ item.text }}</button>
          <span class="toolbar-divider" />
          <button type="button" title="插入链接" aria-label="插入链接" @click="insertLink">链接</button>
          <button type="button" title="插入正文图片" aria-label="插入正文图片" :disabled="uploading" @click="imageVisible = true">图片</button>
          <button type="button" title="插入表格" aria-label="插入表格" @click="editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()">表格</button>
          <template v-if="editor?.isActive('table')">
            <button type="button" @click="editor.chain().focus().addRowAfter().run()">加行</button>
            <button type="button" @click="editor.chain().focus().addColumnAfter().run()">加列</button>
            <button type="button" @click="editor.chain().focus().deleteTable().run()">删表</button>
          </template>
          <span class="toolbar-divider" />
          <button type="button" aria-label="撤销" @click="editor.chain().focus().undo().run()">撤销</button>
          <button type="button" aria-label="重做" @click="editor.chain().focus().redo().run()">重做</button>
        </div>
        <EditorContent :editor="editor" class="article-editor" />
        <div class="document-footer"><span>{{ characterCount }} 字 · {{ imageCount }} 张正文图片</span><span>标题、封面、声明会按平台单独校验</span></div>
        <div class="common-tags">
          <label>默认话题</label><el-input v-model="tagsInput" placeholder="用中文或英文逗号分隔，可留空" @input="markDirty" />
        </div>
      </section>

      <aside class="distribution-panel">
        <div class="distribution-heading"><h2>发布到</h2><span>{{ selectedAccountIds.length }} 个账号</span></div>
        <el-alert v-if="accounts.some((account) => account.needs_confirmation)" type="warning" :closable="false" show-icon>
          旧账号的平台编号存在冲突，请先到 <router-link to="/account-management">账号管理</router-link> 确认所属平台，确认后才能选择发布。
        </el-alert>
        <p class="distribution-caption">选择平台账号；留空的覆盖项沿用文章内容。</p>
        <label class="platform-filter-label" for="article-platform-filter">筛选平台</label>
        <el-select id="article-platform-filter" v-model="platformFilter" aria-label="筛选发布平台" class="platform-filter">
          <el-option :label="`全部平台（${capabilities.length}）`" value="all" />
          <el-option v-for="platform in capabilities" :key="platform.platform" :label="platform.label" :value="platform.platform">
            <span>{{ platform.label }}</span><span class="platform-option-count">{{ accountsFor(platform.platform).length }} 个账号</span>
          </el-option>
        </el-select>
        <p v-if="platformFilter !== 'all'" class="capability-note">筛选只影响展示，其他平台已选账号仍会发布。</p>
        <div v-for="platform in visiblePlatforms" :key="platform.platform" class="platform-section">
          <div class="platform-heading"><span class="platform-mark">{{ platform.label.slice(0, 1) }}</span><h3>{{ platform.label }}</h3></div>
          <p class="capability-note">{{ platform.content_kind || '文章' }} · {{ platform.available === false ? '待接入' : platform.live_verified ? '已完成基础流程验证' : '真实账号待验证' }}</p>
          <p class="capability-note">{{ verificationHint(platform) }}</p>
          <p v-if="platform.verification_scope" class="capability-note">验证范围：{{ platform.verification_scope }}</p>
          <p class="capability-note">{{ titleHint(platform) }} · {{ coverDescription(platform) }}{{ coverHint(platform) }}</p>
          <p v-if="platform.content_mode === 'image_text'" class="capability-note">描述最多 {{ platform.body_max_chars }} 字（含话题），图片 1–{{ platform.body_max_images }} 张（含封面）。</p>
          <p v-if="platform.image_min_width && platform.image_min_height" class="capability-note">每张图片至少 {{ platform.image_min_width }} × {{ platform.image_min_height }} 像素。</p>
          <p v-if="platform.reason || platform.limitations" class="capability-note">{{ platform.reason || platform.limitations }}</p>
          <p v-if="platform.permission_check" class="capability-note">{{ platform.permission_check }}</p>
          <div v-if="accountsFor(platform.platform).length" class="account-options">
            <div v-for="account in accountsFor(platform.platform)" :key="account.id" class="account-option">
              <el-checkbox :disabled="platform.available === false" :model-value="selectedAccountIds.includes(account.id)" @change="toggleAccount(account, $event)">{{ account.user_name }}</el-checkbox>
              <span :class="['account-health', { invalid: !accountIsValid(account) }]">{{ accountIsValid(account) ? '已登录' : '需校验登录' }}</span>
            </div>
          </div>
          <p v-else-if="platform.available !== false" class="empty-account">暂无账号，<router-link to="/account-management">前往添加</router-link></p>
          <details v-for="account in selectedFor(platform.platform)" :key="account.id" class="target-overrides">
            <summary>{{ account.user_name }} · 个性化设置</summary>
            <label>平台标题</label><el-input v-model="targetConfigs[account.id].title" :placeholder="form.title || '沿用文章标题'" @input="markDirty" />
            <small>{{ titleHint(platform) }}</small>
            <template v-if="platform.cover_supported !== false">
            <label>{{ platform.cover_label || '平台封面' }}</label>
            <div class="override-cover">
              <img v-if="targetConfigs[account.id].cover_asset_id" :src="assetUrl(targetConfigs[account.id].cover_asset_id)" alt="平台专用封面" />
              <el-upload :auto-upload="false" :show-file-list="false" accept="image/jpeg,image/png,image/webp" :on-change="(file) => uploadTargetCover(file.raw, account.id)">
                <el-button size="small" :loading="uploading">上传封面</el-button>
              </el-upload>
              <el-button v-if="targetConfigs[account.id].cover_asset_id" text size="small" @click="targetConfigs[account.id].cover_asset_id = null; markDirty()">沿用默认</el-button>
            </div>
            <small>{{ coverDescription(platform) }}{{ coverHint(platform) }}</small>
            </template>
            <small v-else>此平台不设置独立封面，默认封面不会应用到该平台；正文图片正常保留。</small>
            <template v-if="platform.tags_supported !== false">
            <label>话题覆盖</label>
            <el-select v-model="targetConfigs[account.id].tags_mode" @change="markDirty">
              <el-option label="沿用默认话题" value="inherit" /><el-option label="单独设置话题" value="custom" /><el-option label="清空话题" value="clear" />
            </el-select>
            <el-input v-if="targetConfigs[account.id].tags_mode === 'custom'" v-model="targetConfigs[account.id].tags_text" placeholder="用逗号分隔；留空表示清空" @input="markDirty" />
            </template>
            <small v-else>此平台不设置独立话题，默认话题不会应用到该平台。</small>
            <template v-for="field in optionFields(platform)" :key="field.name">
              <label>{{ field.label }}{{ field.required ? '（必填）' : '' }}</label>
              <el-select :model-value="optionMode(account.id, field.name)" @change="setOptionMode(account.id, field, $event)">
                <el-option label="继承平台设置" value="inherit" /><el-option label="单独设置" value="custom" /><el-option label="清空设置" value="clear" />
              </el-select>
              <template v-if="optionMode(account.id, field.name) === 'custom'">
                <el-checkbox v-if="field.type === 'boolean'" v-model="targetConfigs[account.id].options[field.name]" @change="markDirty">{{ field.label }}</el-checkbox>
                <el-select v-else-if="field.type === 'select'" v-model="targetConfigs[account.id].options[field.name]" :placeholder="field.placeholder || '请选择'" clearable @change="markDirty">
                  <el-option v-for="option in field.options || []" :key="statementValue(option)" :label="statementLabel(option)" :value="statementValue(option)" />
                </el-select>
                <div v-else-if="field.type === 'asset'" class="override-cover option-cover">
                  <img v-if="targetConfigs[account.id].options[field.name]" :src="assetUrl(targetConfigs[account.id].options[field.name])" :alt="field.label" />
                  <el-upload :auto-upload="false" accept="image/jpeg,image/png" :show-file-list="false" :on-change="(file) => uploadOptionAsset(file.raw, account.id, field)">
                    <el-button size="small" :loading="uploading">上传{{ field.label }}</el-button>
                  </el-upload>
                  <small v-if="field.placeholder">{{ field.placeholder }}</small>
                </div>
                <el-input v-else v-model="targetConfigs[account.id].options[field.name]" :type="field.type === 'textarea' ? 'textarea' : 'text'" :placeholder="field.placeholder" :maxlength="field.max_length" :show-word-limit="!!field.max_length" @input="markDirty" />
              </template>
              <template v-else-if="optionMode(account.id, field.name) === 'inherit'">
                <small>当前平台设置：{{ inheritedOption(account.platform, field.name, field.type) }}</small>
                <div v-if="field.type === 'asset' && form.platform_options[account.platform]?.options?.[field.name]" class="override-cover option-cover">
                  <img :src="assetUrl(form.platform_options[account.platform].options[field.name])" :alt="field.label" />
                </div>
              </template>
            </template>
          </details>
        </div>
        <div class="publish-controls">
          <el-switch v-model="previewMode" active-text="仅预览，不点击发布" />
          <p v-if="previewMode" class="preview-note">平台可能自动保存草稿；预览完成不代表已发布。</p>
          <el-button type="primary" :loading="publishing" :disabled="!selectedAccountIds.length || !!loadError || uploading" class="publish-button" @click="submitPublication">
            {{ previewMode ? '提交平台预览' : `发布到 ${selectedAccountIds.length || '所选'} 个账号` }}
          </el-button>
          <p class="publish-note">{{ previewMode ? '预览结果会保留在下方记录中。' : '保存当前修订后直接发布，各账号独立执行。' }}</p>
        </div>
      </aside>
    </div>

    <section class="history-panel">
      <div class="history-heading"><div><h2>发布记录</h2><p>平台受理、公开发表与结果不确定分别记录。</p></div><el-button text :loading="refreshing" :disabled="!form.id" @click="refreshBatches">刷新记录</el-button></div>
      <div v-if="!batches.length" class="history-empty">提交文章后，这里会显示每个平台账号的实际进度。</div>
      <article v-for="batch in batches" :key="batch.id" class="batch-record">
        <div class="batch-heading"><span>修订 {{ batch.revision }} · {{ batch.mode === 'preview' ? '平台预览' : '直接发布' }}</span><span>{{ formatTime(batch.created_at) }}</span></div>
        <div v-for="task in batch.tasks || []" :key="task.id" class="task-row">
          <div class="task-identity"><strong>{{ platformLabel(task.platform) }}</strong><span>{{ accountLabel(task.account_id) }}</span></div>
          <el-tag :type="statusType(task.status)" effect="light">{{ statusLabel(task.status) }}</el-tag>
          <div class="task-detail"><span>{{ task.message || stageLabel(task.stage) }}</span><small v-if="task.platform_status">平台状态：{{ task.platform_status }}</small></div>
          <div class="task-actions">
            <el-link v-if="safePlatformUrl(task.platform_url)" :href="task.platform_url" target="_blank" rel="noopener noreferrer">平台内容</el-link>
            <el-button v-if="task.evidence?.length" text size="small" @click="showEvidence(task)">查看证据</el-button>
            <el-button v-if="task.retry_allowed && ['failed', 'needs_action'].includes(task.status)" text type="primary" size="small" @click="retryTask(task)">{{ task.status === 'needs_action' ? '完成操作后重试' : '重试此账号' }}</el-button>
            <el-button v-if="task.status === 'unknown'" text type="warning" size="small" @click="openResolution(task)">记录人工核查</el-button>
            <el-button v-if="task.status === 'submitted'" text type="primary" size="small" @click="openResolution(task)">核对公开发表</el-button>
          </div>
        </div>
      </article>
    </section>

    <el-dialog v-model="importVisible" title="导入文章内容" width="min(660px, calc(100vw - 24px))">
      <p class="dialog-note">导入会替换当前正文。图片会在保存时导入为本地素材。</p>
      <el-radio-group v-model="importFormat"><el-radio-button value="markdown">Markdown</el-radio-button><el-radio-button value="html">HTML</el-radio-button><el-radio-button value="text">纯文本</el-radio-button></el-radio-group>
      <el-input v-model="importContent" type="textarea" :rows="12" placeholder="粘贴文章正文" class="import-input" />
      <input type="file" accept=".md,.markdown,.html,.htm,.txt" @change="readImportFile" />
      <template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!importContent.trim()" @click="importArticle">导入并保存</el-button></template>
    </el-dialog>
    <el-dialog v-model="imageVisible" title="插入正文图片" width="min(480px, calc(100vw - 24px))">
      <p class="dialog-note">本地图片或公开图片地址都会保存到文章素材库。</p>
      <el-upload drag :auto-upload="false" :show-file-list="false" multiple accept="image/jpeg,image/png,image/webp" :on-change="(file) => insertImageFile(file.raw)">
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon><div>拖入图片，或点击选择</div>
      </el-upload>
      <div class="image-url"><el-input v-model="imageUrlInput" placeholder="https://… 图片地址" /><el-button :loading="uploading" :disabled="!imageUrlInput.trim()" @click="insertRemoteImage">导入图片</el-button></div>
    </el-dialog>
    <el-dialog v-model="evidenceVisible" title="任务证据" width="min(800px, calc(100vw - 24px))">
      <template v-for="url in evidenceUrls" :key="url">
        <img v-if="/\.(png|jpe?g|webp)(?:$|\?)/i.test(url)" :src="url" alt="平台发布任务截图" class="evidence-image" />
        <el-link v-else :href="url" target="_blank" rel="noopener noreferrer">打开证据文件</el-link>
      </template>
    </el-dialog>
    <el-dialog v-model="resolveVisible" :title="publishedOnlyResolution ? '核对公开发表' : '记录人工核查结果'" width="min(520px, calc(100vw - 24px))">
      <el-alert type="warning" :closable="false" :title="publishedOnlyResolution ? '请确认文章已公开可访问，并填写公开文章链接和核查说明。此处只记录已公开发表的核查结果。' : '先到平台核查是否已有文章。结果不确定的任务不会自动重发。'" />
      <el-form label-position="top" class="resolution-form">
        <el-form-item label="核查结果"><el-select v-model="resolution.resolution"><el-option v-if="!publishedOnlyResolution" label="确认没有发布，可以重试" value="not_published" /><el-option v-if="!publishedOnlyResolution" label="平台已受理，正在审核" value="submitted" /><el-option label="确认已经公开发表" value="published" /></el-select></el-form-item>
        <el-form-item label="平台文章链接" :required="publishedOnlyResolution"><el-input v-model="resolution.platform_url" :placeholder="publishedOnlyResolution ? '必填：http:// 或 https:// 公开文章链接' : '已受理或已发表时建议填写'" /></el-form-item>
        <el-form-item label="核查说明" :required="publishedOnlyResolution"><el-input v-model="resolution.note" type="textarea" :rows="3" :placeholder="publishedOnlyResolution ? '必填：记录公开访问及内容核对情况' : '记录平台核查情况'" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resolveVisible = false">取消</el-button><el-button type="primary" :loading="resolving" @click="resolveTask">保存核查结果</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Close, Picture, Plus, UploadFilled } from '@element-plus/icons-vue'
import { EditorContent, useEditor } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import { TableKit } from '@tiptap/extension-table'
import { articleUrl, articlesApi } from '@/api/articles'

const articles = ref([])
const accounts = ref([])
const capabilities = ref([])
const platformFilter = ref('all')
const visiblePlatforms = computed(() => capabilities.value.filter((platform) => platformFilter.value === 'all' || platform.platform === platformFilter.value))
const batches = ref([])
const search = ref('')
const initialLoading = ref(true)
const loadError = ref('')
const dirty = ref(false)
const saving = ref(false)
const publishing = ref(false)
const refreshing = ref(false)
const uploading = ref(false)
const previewMode = ref(false)
const revisionConflict = ref(false)
const tagsInput = ref('')
const selectedAccountIds = ref([])
const targetConfigs = reactive({})
const coverInput = ref(null)
const importVisible = ref(false)
const importFormat = ref('markdown')
const importContent = ref('')
const imageVisible = ref(false)
const imageUrlInput = ref('')
const evidenceVisible = ref(false)
const evidenceUrls = ref([])
const resolveVisible = ref(false)
const resolving = ref(false)
const resolutionTask = ref(null)
const publishedOnlyResolution = computed(() => resolutionTask.value?.status === 'submitted')
const resolution = reactive({ resolution: 'not_published', platform_url: '', note: '' })
const form = reactive({ id: null, title: '', revision: null, cover_asset_id: null, platform_options: {} })
let pollingTimer = null
let loadSequence = 0
let batchFetchSequence = 0
let activeUploads = 0

// 图片保留素材 ID；渲染 URL 使用后端地址，导出时仍能精确定位本地素材。
const ArticleImage = Image.extend({
  addAttributes() {
    return { ...this.parent?.(), assetId: { default: null, parseHTML: (el) => el.getAttribute('data-asset-id'), renderHTML: (attrs) => attrs.assetId ? { 'data-asset-id': attrs.assetId } : {} } }
  }
})
const editor = useEditor({
  extensions: [StarterKit.configure({ heading: { levels: [1, 2, 3, 4, 5, 6] }, link: { openOnClick: false, isAllowedUri: (url) => isArticleLink(url) } }), ArticleImage, TableKit.configure({ table: { resizable: true } })],
  content: '<p></p>',
  editorProps: { attributes: { 'aria-label': '文章正文编辑器' } },
  onUpdate: () => markDirty()
})
const formatTools = [
  { label: '正文段落', text: '正文', active: 'paragraph', run: () => editor.value.chain().focus().setParagraph().run() },
  { label: '一级标题', text: 'H1', active: 'heading', attrs: { level: 1 }, run: () => editor.value.chain().focus().toggleHeading({ level: 1 }).run() },
  { label: '二级标题', text: 'H2', active: 'heading', attrs: { level: 2 }, run: () => editor.value.chain().focus().toggleHeading({ level: 2 }).run() },
  { label: '三级标题', text: 'H3', active: 'heading', attrs: { level: 3 }, run: () => editor.value.chain().focus().toggleHeading({ level: 3 }).run() },
  { label: '加粗', text: '粗体', active: 'bold', run: () => editor.value.chain().focus().toggleBold().run() },
  { label: '斜体', text: '斜体', active: 'italic', run: () => editor.value.chain().focus().toggleItalic().run() },
  { label: '无序列表', text: '列表', active: 'bulletList', run: () => editor.value.chain().focus().toggleBulletList().run() },
  { label: '有序列表', text: '编号', active: 'orderedList', run: () => editor.value.chain().focus().toggleOrderedList().run() },
  { label: '引用', text: '引用', active: 'blockquote', run: () => editor.value.chain().focus().toggleBlockquote().run() }
]
const filteredArticles = computed(() => articles.value.filter((item) => (item.title || '').toLowerCase().includes(search.value.toLowerCase())))
const characterCount = computed(() => editor.value?.getText().replace(/\s/g, '').length || 0)
const imageCount = computed(() => (editor.value?.getHTML().match(/<img\b/g) || []).length)

// 所有编辑入口统一标记未保存状态，离开页面时保护用户正文。
function markDirty() { dirty.value = true }
function startUpload() { activeUploads++; uploading.value = true }
function finishUpload() { activeUploads--; uploading.value = activeUploads > 0 }
function parseTags(value) { return value.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean) }
function assetUrl(id) { return articleUrl(`/api/article-assets/${id}/content`) }
function accountsFor(platform) { return accounts.value.filter((account) => account.platform === platform) }
function selectedFor(platform) { return accountsFor(platform).filter((account) => selectedAccountIds.value.includes(account.id)) }
function accountIsValid(account) { return account.status === 1 || account.status === 'valid' || account.status === '正常' }
function platformLabel(platform) { return capabilities.value.find((item) => item.platform === platform)?.label || platform }
function accountLabel(id) { return accounts.value.find((item) => item.id === id)?.user_name || `账号 ${id}` }
function statementValue(option) { return typeof option === 'string' ? option : option.value }
function statementLabel(option) { return typeof option === 'string' ? option : option.label }
// 兼容旧能力字段，服务端声明的新字段优先，避免重复显示声明与 AI 开关。
function optionFields(platform) {
  const fields = [...(platform.option_fields || [])]
  if (platform.statement_options?.length && !fields.some((field) => field.name === 'statement')) fields.push({ name: 'statement', label: '创作声明', type: 'select', options: platform.statement_options })
  if (platform.platform === 'baijiahao' && !fields.some((field) => field.name === 'ai_generated')) fields.push({ name: 'ai_generated', label: '含 AI 生成内容', type: 'boolean' })
  return fields
}
// 三态区分继承、覆盖和清空，布尔 false 也属于明确覆盖。
function optionMode(id, name) { return targetConfigs[id].option_modes[name] || 'inherit' }
function setOptionMode(id, field, mode) {
  const config = targetConfigs[id]
  config.option_modes[field.name] = mode
  if (mode === 'custom' && config.options[field.name] == null) config.options[field.name] = field.type === 'boolean' ? false : ''
  markDirty()
}
function inheritedOption(platform, name, type) {
  const value = form.platform_options[platform]?.options?.[name]
  if (type === 'asset') return value ? '已上传封面' : '未设置'
  return value == null || value === '' ? '平台默认' : typeof value === 'boolean' ? (value ? '是' : '否') : value
}
// 未知配置一并保留，能力版本升级后再次保存不会丢失原配置。
function resolvedOptions(account, config) {
  const options = { ...(form.platform_options[account.platform]?.options || {}), ...config.options }
  const platform = capabilities.value.find((item) => item.platform === account.platform)
  optionFields(platform || {}).forEach((field) => {
    const mode = optionMode(account.id, field.name)
    if (mode === 'inherit') {
      const original = form.platform_options[account.platform]?.options || {}
      if (Object.hasOwn(original, field.name)) options[field.name] = original[field.name]
      else delete options[field.name]
    } else if (mode === 'clear') options[field.name] = field.type === 'boolean' ? false : ''
  })
  return options
}
function verificationHint(platform) {
  const verification = platform.verification || {}
  return [['preview', '预览'], ['submitted', '受理'], ['published', '公开发表']].map(([key, label]) => `${label}：${verification[key] ? '已验证' : '待验证'}`).join(' · ')
}
function titleHint(platform) {
  if (platform.title_weighted_limits) return `标题 ${platform.title_weighted_limits[0]}–${platform.title_weighted_limits[1]} 字（英文字符按半字计）`
  const limit = platform.title_limit_confirmed === false ? '标题按平台页面限制校验，原稿最多 300 字' : `标题 ${platform.title_min || 1}–${platform.title_max || '不限'} 字`
  return limit + (platform.title_min_cjk ? `，至少 ${platform.title_min_cjk} 个汉字` : '')
}
function coverDescription(platform) {
  return platform.cover_supported === false ? '不设置独立封面' : platform.cover_required ? '必须有封面' : '封面可选'
}
function coverHint(platform) {
  if (platform.cover_supported === false) return ''
  if (platform.cover_hint) return `，${platform.cover_hint}`
  const size = platform.cover_max_bytes ? `，最大 ${Math.round(platform.cover_max_bytes / 1024 / 1024)} MB` : ''
  const dimensions = platform.cover_min_width && platform.cover_min_height ? `，需大于 ${platform.cover_min_width} × ${platform.cover_min_height}` : ''
  return size + dimensions
}
function formatTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
function statusLabel(status) {
  return ({ queued: '等待执行', running: '执行中', needs_action: '需要人工操作', previewed: '预览完成', submitted: '平台已受理', published: '已公开发表', failed: '执行失败', unknown: '结果不确定' })[status] || status
}
function statusType(status) {
  if (['published', 'previewed'].includes(status)) return 'success'
  if (status === 'failed') return 'danger'
  if (['unknown', 'needs_action'].includes(status)) return 'warning'
  return 'info'
}
function stageLabel(stage) { return ({ queued: '等待执行', preparing: '准备内容', submitting: '已开始提交，等待平台回执', finished: '执行结束', validation: '平台参数校验未通过' })[stage] || stage || '等待更新' }
function safePlatformUrl(value) { return /^https?:\/\//i.test(value || '') }
// 编辑器与后端统一接受完整的 HTTP/HTTPS 地址，避免保存后静默删除其他协议。
function isArticleLink(value) {
  if (!/^https?:\/\//i.test(value || '')) return false
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !!url.hostname }
  catch { return false }
}

// 账号首次勾选沿用平台默认设置；每个账号之后可独立覆盖。
function toggleAccount(account, selected) {
  const platform = capabilities.value.find((item) => item.platform === account.platform)
  if (selected && platform?.available === false) return
  if (selected) {
    selectedAccountIds.value = [...new Set([...selectedAccountIds.value, account.id])]
    if (!targetConfigs[account.id]) {
      const defaults = form.platform_options[account.platform] || {}
      targetConfigs[account.id] = { title: defaults.title || '', cover_asset_id: defaults.cover_asset_id || null, tags_text: (defaults.tags || []).join('，'), tags_mode: Array.isArray(defaults.tags) ? (defaults.tags.length ? 'custom' : 'clear') : 'inherit', options: { ...(defaults.options || {}) }, option_modes: {} }
      if (platform?.cover_supported === false) targetConfigs[account.id].cover_asset_id = null
      if (platform?.tags_supported === false) targetConfigs[account.id].tags_mode = 'clear'
    }
  } else selectedAccountIds.value = selectedAccountIds.value.filter((id) => id !== account.id)
}

// 保存每个平台第一个所选账号的设置为下次默认；本次各账号仍保留独立覆盖。
function collectPlatformOptions() {
  const defaults = { ...form.platform_options }
  const seen = new Set()
  selectedAccountIds.value.forEach((id) => {
    const account = accounts.value.find((item) => item.id === id)
    if (!account || seen.has(account.platform)) return
    seen.add(account.platform)
    const config = targetConfigs[id]
    defaults[account.platform] = {
      ...(defaults[account.platform] || {}),
      title: config.title.trim() || null,
      cover_asset_id: config.cover_asset_id || null,
      tags: config.tags_mode === 'inherit' ? null : config.tags_mode === 'clear' ? [] : parseTags(config.tags_text),
      options: resolvedOptions(account, config)
    }
  })
  return defaults
}

// 切换稿件前征询未保存修改；取消时保持当前编辑器和任务记录。
async function confirmDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，离开会丢失这些修改。', '保留编辑内容', { confirmButtonText: '放弃修改并离开', cancelButtonText: '继续编辑', type: 'warning' })
    return true
  } catch { return false }
}
async function createDraft() {
  if (!(await confirmDiscard())) return
  loadSequence++
  Object.assign(form, { id: null, title: '', revision: null, cover_asset_id: null, platform_options: {} })
  editor.value?.commands.setContent('<p></p>', { emitUpdate: false })
  tagsInput.value = ''
  batches.value = []
  selectedAccountIds.value = []
  Object.keys(targetConfigs).forEach((key) => delete targetConfigs[key])
  dirty.value = false
  revisionConflict.value = false
}
// 后端返回的清洗 HTML 为最终稿件；仅将已管理素材的相对 URL 转为可显示地址。
function loadArticle(article) {
  Object.assign(form, { id: article.id, title: article.title || '', revision: article.revision, cover_asset_id: article.cover_asset_id || null, platform_options: article.platform_options || {} })
  const document = new DOMParser().parseFromString(article.content_html || '<p></p>', 'text/html')
  document.querySelectorAll('img').forEach((img) => {
    const source = img.getAttribute('src') || ''
    if (source.startsWith('/api/article-assets/')) img.setAttribute('src', articleUrl(source))
  })
  editor.value?.commands.setContent(document.body.innerHTML, { emitUpdate: false })
  tagsInput.value = (article.tags || []).join('，')
  dirty.value = false
  revisionConflict.value = false
}
async function openArticle(id) {
  if (id === form.id || !(await confirmDiscard())) return
  const sequence = ++loadSequence
  try {
    const response = await articlesApi.get(id)
    if (sequence !== loadSequence) return
    loadArticle(response.data)
    batches.value = []
    selectedAccountIds.value = []
    Object.keys(targetConfigs).forEach((key) => delete targetConfigs[key])
    await refreshBatches()
  } catch { /* 请求拦截器统一展示错误，当前稿件保持不变。 */ }
}
async function reloadArticle() {
  if (!form.id || !(await confirmDiscard())) return
  const response = await articlesApi.get(form.id)
  loadArticle(response.data)
}
// 保存使用修订号做乐观锁；冲突或网络失败时绝不清空正文。
async function saveArticle(contentOverride = null) {
  if (saving.value) return null
  if (uploading.value) { ElMessage.warning('请等待图片上传完成'); return null }
  if (!form.title.trim()) { ElMessage.warning('请先填写文章标题'); return null }
  saving.value = true
  const payload = { title: form.title.trim(), content: contentOverride?.content ?? editor.value.getHTML(), format: contentOverride?.format || 'html', cover_asset_id: form.cover_asset_id, tags: parseTags(tagsInput.value), platform_options: collectPlatformOptions() }
  try {
    const response = form.id ? await articlesApi.update(form.id, { ...payload, expected_revision: form.revision }) : await articlesApi.create(payload)
    loadArticle(response.data)
    articles.value = [response.data, ...articles.value.filter((article) => article.id !== response.data.id)]
    ElMessage.success('文章已保存')
    return response.data
  } catch (error) {
    if (error.response?.status === 409) revisionConflict.value = true
    return null
  } finally { saving.value = false }
}
function removeCover() { form.cover_asset_id = null; markDirty() }
async function uploadCover(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  startUpload()
  try { const response = await articlesApi.uploadAsset(file); form.cover_asset_id = response.data.id; markDirty() }
  catch { /* 保留原封面，请求层显示上传失败。 */ }
  finally { finishUpload() }
}
async function uploadTargetCover(file, accountId) {
  if (!file) return
  startUpload()
  try { const response = await articlesApi.uploadAsset(file); targetConfigs[accountId].cover_asset_id = response.data.id; markDirty() }
  catch { /* 平台原有覆盖设置保持不变。 */ }
  finally { finishUpload() }
}
async function uploadOptionAsset(file, accountId, field) {
  if (!file) return
  startUpload()
  try {
    const response = await articlesApi.uploadAsset(file)
    targetConfigs[accountId].options[field.name] = response.data.id
    markDirty()
  } catch { /* 保留原素材，上传失败由请求层提示。 */ }
  finally { finishUpload() }
}
// 图片由后端存储后才插入，正文不依赖用户电脑的临时文件路径。
async function insertImageFile(file) {
  if (!file) return
  startUpload()
  try {
    const response = await articlesApi.uploadAsset(file)
    editor.value.chain().focus().setImage({ src: articleUrl(response.data.url), alt: file.name, assetId: response.data.id }).run()
    imageVisible.value = false
  } catch { /* 上传失败不插入失效图片。 */ }
  finally { finishUpload() }
}
async function insertRemoteImage() {
  startUpload()
  try {
    const response = await articlesApi.importAsset(imageUrlInput.value.trim())
    editor.value.chain().focus().setImage({ src: articleUrl(response.data.url), alt: response.data.filename || '', assetId: response.data.id }).run()
    imageVisible.value = false
    imageUrlInput.value = ''
  } catch { /* 远程地址由后端校验。 */ }
  finally { finishUpload() }
}
async function insertLink() {
  try {
    const { value } = await ElMessageBox.prompt('输入完整的 HTTP 或 HTTPS 链接；留空可移除当前链接。', '插入链接', { inputValue: editor.value.getAttributes('link').href || '', inputValidator: (value) => !value || isArticleLink(value) || '请输入完整的 HTTP 或 HTTPS 地址', confirmButtonText: '确定', cancelButtonText: '取消' })
    const chain = editor.value.chain().focus().extendMarkRange('link')
    value ? chain.setLink({ href: value }).run() : chain.unsetLink().run()
  } catch { /* 取消输入不修改正文。 */ }
}
async function readImportFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importContent.value = await file.text()
  importFormat.value = /\.html?$/i.test(file.name) ? 'html' : /\.(md|markdown)$/i.test(file.name) ? 'markdown' : 'text'
  event.target.value = ''
}
async function importArticle() {
  const article = await saveArticle({ content: importContent.value, format: importFormat.value })
  if (article) { importVisible.value = false; importContent.value = '' }
}

// 同一修订、相同目标与模式复用幂等键；请求超时及页面刷新不会产生新的提交。
function submissionKey(articleId, payload) {
  const fingerprint = JSON.stringify({ article_id: articleId, ...payload })
  const storageKey = 'omnipost:article-publication-keys'
  let entries = []
  try { entries = JSON.parse(sessionStorage.getItem(storageKey) || '[]') } catch { /* 存储不可用时使用内存回退。 */ }
  const existing = entries.find((entry) => entry.fingerprint === fingerprint)
  if (existing) return existing.key
  const key = globalThis.crypto?.randomUUID?.() || `article-${Date.now()}-${Math.random().toString(36).slice(2)}`
  entries.push({ fingerprint, key })
  try { sessionStorage.setItem(storageKey, JSON.stringify(entries.slice(-100))) } catch { /* 后端修订与目标去重继续保护重复提交。 */ }
  return key
}
async function submitPublication() {
  if (publishing.value || saving.value || !selectedAccountIds.value.length) return
  publishing.value = true
  try {
    if (dirty.value || !form.id) {
      const saved = await saveArticle()
      if (!saved) return
    }
    const targets = selectedAccountIds.value.map((id) => {
      const account = accounts.value.find((item) => item.id === id)
      const config = targetConfigs[id]
      const options = resolvedOptions(account, config)
      const platform = capabilities.value.find((item) => item.platform === account.platform)
      const overrides = { title: config.title.trim() || form.title, cover_asset_id: platform?.cover_supported === false ? null : config.cover_asset_id || form.cover_asset_id || null, options }
      // 沿用时不发送 tags；显式空数组让用户可以清除文章默认话题。
      if (config.tags_mode !== 'inherit') overrides.tags = config.tags_mode === 'clear' ? [] : parseTags(config.tags_text)
      return { platform: account.platform, account_id: id, overrides }
    })
    // 后端按目标逐项校验并记录失败，单个平台参数不合要求不阻塞其他账号。
    const payload = { revision: form.revision, targets, mode: previewMode.value ? 'preview' : 'publish' }
    const response = await articlesApi.publish(form.id, { ...payload, idempotency_key: submissionKey(form.id, payload) })
    batches.value = [response.data, ...batches.value.filter((batch) => batch.id !== response.data.id)]
    ElMessage.info('任务已提交，实际平台结果会显示在发布记录中')
    await refreshBatches()
  } catch { await refreshBatches() }
  finally { publishing.value = false }
}
// 轮询批次详情；切换稿件后的旧请求不得覆盖新稿件记录。
async function refreshBatches() {
  if (!form.id) return
  const articleId = form.id
  const sequence = ++batchFetchSequence
  refreshing.value = true
  try {
    const response = await articlesApi.batches(articleId)
    const listed = response.data.items || response.data || []
    const results = await Promise.all(listed.map((batch) => articlesApi.batch(batch.id)))
    if (form.id === articleId && sequence === batchFetchSequence) batches.value = results.map((item) => item.data)
  } catch { /* 查询失败保留最近一次任务记录，后续刷新继续核对。 */ }
  finally { if (sequence === batchFetchSequence) refreshing.value = false }
}
async function retryTask(task) {
  try { await articlesApi.retry(task.id); ElMessage.info('此账号重试任务已提交'); await refreshBatches() }
  catch { /* 后端再次校验可重试状态。 */ }
}
function showEvidence(task) {
  evidenceUrls.value = task.evidence.map((entry) => articleUrl(typeof entry === 'string' ? entry : entry.url)).filter(Boolean)
  evidenceVisible.value = true
}
function openResolution(task) {
  // 已受理任务只能记录公开发表；结果不确定任务仍保留原核查选项。
  resolutionTask.value = task
  Object.assign(resolution, { resolution: task.status === 'submitted' ? 'published' : 'not_published', platform_url: task.platform_url || '', note: '' })
  resolveVisible.value = true
}
async function resolveTask() {
  // 公开发表核查必须有完整的 HTTP(S) 链接和说明，不能降级已受理任务。
  if (publishedOnlyResolution.value) {
    let publicUrl
    try { publicUrl = new URL(resolution.platform_url.trim()) } catch { /* 无效地址交由下面的校验提示。 */ }
    if (!publicUrl || !['http:', 'https:'].includes(publicUrl.protocol) || !publicUrl.hostname) { ElMessage.warning('请填写有效的 http 或 https 公开文章链接'); return }
    if (!resolution.note.trim()) { ElMessage.warning('请填写公开发表的核查说明'); return }
    if (resolution.resolution !== 'published') { ElMessage.warning('已受理任务只能核查为已公开发表'); return }
  }
  if (resolution.platform_url && !safePlatformUrl(resolution.platform_url)) { ElMessage.warning('平台链接须以 http 或 https 开头'); return }
  resolving.value = true
  try { await articlesApi.resolve(resolutionTask.value.id, { ...resolution }); resolveVisible.value = false; await refreshBatches() }
  catch { /* 核查记录保存失败时保留输入。 */ }
  finally { resolving.value = false }
}
function beforeUnload(event) { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(() => confirmDiscard())
onMounted(async () => {
  window.addEventListener('beforeunload', beforeUnload)
  try {
    const [articleResponse, accountResponse, capabilityResponse] = await Promise.all([articlesApi.list(), articlesApi.accounts(), articlesApi.capabilities()])
    articles.value = articleResponse.data.items || articleResponse.data || []
    accounts.value = accountResponse.data.items || accountResponse.data || []
    capabilities.value = capabilityResponse.data.platforms || []
    if (articles.value.length) { const response = await articlesApi.get(articles.value[0].id); loadArticle(response.data); await refreshBatches() }
    pollingTimer = window.setInterval(() => {
      if (!document.hidden && !refreshing.value && batches.value.some((batch) => (batch.tasks || []).some((task) => ['queued', 'running', 'needs_action'].includes(task.status)))) refreshBatches()
    }, 4000)
  } catch { loadError.value = '文章工作台暂时无法加载，请确认后端已经升级并启动。' }
  finally { initialLoading.value = false }
})
onBeforeUnmount(() => { clearInterval(pollingTimer); window.removeEventListener('beforeunload', beforeUnload); editor.value?.destroy() })
</script>

<style scoped>
.article-workspace { --ink: #253735; --muted: #71817b; --line: #e1e7e2; --accent: #2d6758; color: var(--ink); max-width: 1800px; margin: 0 auto; }
.workspace-header { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 26px; }
.workspace-kicker { color: var(--accent); font-size: 12px; letter-spacing: .12em; margin: 0 0 9px; }
h1 { font-family: 'Songti SC', 'Noto Serif CJK SC', serif; font-size: 30px; font-weight: 600; margin: 0 0 10px; letter-spacing: .04em; }
.workspace-description { color: var(--muted); font-size: 13px; margin: 0; line-height: 1.7; }
.load-error { margin-bottom: 20px; }
.workspace-grid { display: grid; grid-template-columns: 210px minmax(360px, 1fr) 296px; align-items: start; gap: 20px; }
.draft-rail { padding: 17px 0; }
.rail-heading, .distribution-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; font-size: 14px; font-weight: 600; }
.rail-heading > span:last-child, .distribution-heading > span { font-size: 12px; color: var(--muted); font-weight: 400; }
.draft-list { margin-top: 12px; max-height: 760px; overflow-y: auto; }
.draft-row { width: 100%; background: transparent; border: 0; border-left: 3px solid transparent; text-align: left; padding: 17px 11px; cursor: pointer; border-bottom: 1px solid var(--line); color: var(--ink); transition: background .15s; }
.draft-row:hover { background: #e9eee9; }
.draft-row.selected { background: #e7eeea; border-left-color: var(--accent); }
.draft-title { display: block; font-size: 13px; line-height: 1.7; font-weight: 600; overflow-wrap: anywhere; }
.draft-meta { display: block; margin-top: 8px; color: var(--muted); font-size: 11px; line-height: 1.5; }
.empty-note { font-size: 12px; color: var(--muted); line-height: 1.7; padding: 15px 8px; }
.writing-panel { background: #fff; border: 1px solid var(--line); border-radius: 5px; min-width: 0; box-shadow: 0 4px 14px #25373506; }
.writing-topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding: 14px 22px; }
.save-state { color: var(--muted); font-size: 12px; display: flex; gap: 7px; align-items: center; }
.state-dot { width: 6px; height: 6px; border-radius: 50%; background: #769384; }
.state-dot.dirty { background: #ba8b45; }
.writing-actions { display: flex; gap: 5px; }
.document-cover { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 25px 30px 8px; }
.document-cover > span { font-size: 11px; color: var(--muted); }
.cover-upload { border: 0; background: #f0f4f0; color: #527164; border-radius: 4px; padding: 9px 12px; font-size: 12px; cursor: pointer; display: flex; align-items: center; gap: 6px; }
.cover-thumbnail { position: relative; }
.cover-thumbnail img { width: 106px; height: 64px; object-fit: cover; border-radius: 3px; }
.cover-thumbnail .el-button { position: absolute; top: -7px; right: -7px; }
.document-title { padding: 10px 30px 22px; box-sizing: border-box; }
.document-title :deep(.el-input__wrapper) { box-shadow: none; padding: 0; }
.document-title :deep(.el-input__inner) { font-family: 'Songti SC', 'Noto Serif CJK SC', serif; font-size: 26px; line-height: 1.6; height: 52px; font-weight: 600; color: var(--ink); }
.editor-toolbar { position: sticky; top: -20px; z-index: 2; background: #fafcf9; display: flex; gap: 3px; align-items: center; flex-wrap: wrap; padding: 11px 17px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.editor-toolbar button { border: 0; background: none; color: #5a6b62; font-size: 12px; padding: 7px 8px; border-radius: 3px; cursor: pointer; }
.editor-toolbar button:hover, .editor-toolbar button.active { background: #e0ebe5; color: var(--accent); }
.toolbar-divider { height: 16px; width: 1px; background: #d8e2db; margin: 0 3px; }
.article-editor :deep(.tiptap) { padding: 28px 32px 40px; min-height: 420px; outline: none; font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; line-height: 1.9; font-size: 15px; color: #34423d; overflow-wrap: anywhere; }
.article-editor :deep(.tiptap > :first-child) { margin-top: 0; }
.article-editor :deep(.tiptap p) { margin: 0 0 18px; }
.article-editor :deep(.tiptap h2) { font-family: 'Songti SC', 'Noto Serif CJK SC', serif; font-size: 23px; margin: 30px 0 15px; color: var(--ink); }
.article-editor :deep(.tiptap h3) { font-size: 18px; margin: 25px 0 12px; }
.article-editor :deep(.tiptap img) { max-width: 100%; height: auto; display: block; margin: 22px auto; border-radius: 3px; }
.article-editor :deep(.tiptap img.ProseMirror-selectednode) { outline: 2px solid var(--accent); }
.article-editor :deep(.tiptap blockquote) { margin: 20px 0; border-left: 3px solid #8fa99a; padding-left: 18px; color: var(--muted); }
.article-editor :deep(.tiptap a) { color: var(--accent); text-decoration: underline; }
.article-editor :deep(.tiptap .tableWrapper) { overflow-x: auto; margin: 22px 0; }
.article-editor :deep(.tiptap table) { border-collapse: collapse; table-layout: fixed; width: 100%; }
.article-editor :deep(.tiptap td), .article-editor :deep(.tiptap th) { border: 1px solid #cbd7cd; min-width: 80px; padding: 8px 12px; position: relative; vertical-align: top; }
.article-editor :deep(.tiptap th) { background: #f0f4ef; font-weight: 600; }
.article-editor :deep(.tiptap .selectedCell) { background: #e5eee8; }
.document-footer { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding: 15px 24px; color: var(--muted); font-size: 11px; border-top: 1px solid var(--line); }
.common-tags { display: flex; align-items: center; gap: 16px; padding: 17px 24px; border-top: 1px solid var(--line); }
.common-tags label { flex: 0 0 auto; font-size: 12px; color: var(--muted); }
.distribution-panel { background: #f9fbf8; border: 1px solid var(--line); padding: 22px 20px; border-radius: 5px; }
.distribution-heading h2 { font-size: 17px; margin: 0; font-weight: 600; }
.distribution-caption { font-size: 12px; color: var(--muted); line-height: 1.7; margin: 0 0 14px; }
.platform-filter-label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 7px; }
.platform-filter { width: 100%; margin-bottom: 15px; }
.platform-option-count { float: right; margin-left: 20px; color: var(--muted); font-size: 11px; }
.platform-section { padding: 18px 0; border-top: 1px solid var(--line); }
.platform-heading { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
.platform-heading h3 { font-size: 14px; margin: 0; }
.platform-mark { width: 27px; height: 27px; background: #e7eeea; color: #456a59; display: grid; place-items: center; border-radius: 5px; font-size: 13px; }
.account-option { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.account-option :deep(.el-checkbox) { max-width: 166px; }
.account-option :deep(.el-checkbox__label) { overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
.account-health { font-size: 10px; color: #7c9485; flex-shrink: 0; }
.account-health.invalid { color: #b28a53; }
.capability-note { font-size: 11px; color: var(--muted); line-height: 1.6; overflow-wrap: anywhere; }
.empty-account { font-size: 12px; color: var(--muted); margin: 9px 0 0; }
.empty-account a { color: var(--accent); }
.target-overrides { padding-top: 12px; }
.target-overrides summary { font-size: 11px; color: var(--accent); cursor: pointer; margin-bottom: 10px; overflow-wrap: anywhere; }
.target-overrides label { display: block; margin: 12px 0 6px; font-size: 11px; color: #66796d; }
.target-overrides small { display: block; font-size: 10px; color: var(--muted); margin-top: 5px; line-height: 1.5; }
.target-overrides :deep(.el-select) { width: 100%; }
.target-overrides :deep(.el-checkbox) { max-width: 100%; height: auto; align-items: flex-start; white-space: normal; }
.target-overrides :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; overflow-wrap: anywhere; }
.target-overrides :deep(.el-checkbox__input) { margin-top: 4px; }
.override-cover { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
.override-cover img { width: 56px; height: 36px; object-fit: cover; }
.option-cover img { width: 54px; height: 72px; object-fit: contain; }
.option-cover small { flex-basis: 100%; }
.publish-controls { padding-top: 18px; border-top: 1px solid var(--line); }
.publish-controls :deep(.el-switch__label) { font-size: 12px; }
.publish-button { width: 100%; margin: 16px 0 9px; background: var(--accent); border-color: var(--accent); }
.publish-note, .preview-note { font-size: 11px; line-height: 1.7; color: var(--muted); margin: 0; }
.preview-note { color: #a48450; margin-top: 10px; }
.history-panel { margin-top: 30px; background: #fff; border: 1px solid var(--line); border-radius: 5px; padding: 24px 28px; }
.history-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.history-heading h2 { font-size: 18px; margin: 0 0 7px; font-weight: 600; }
.history-heading p { font-size: 12px; color: var(--muted); margin: 0; }
.history-empty { color: var(--muted); font-size: 13px; padding: 30px 0; text-align: center; }
.batch-record { margin-top: 18px; }
.batch-heading { display: flex; justify-content: space-between; gap: 15px; background: #f4f7f3; padding: 11px 14px; font-size: 12px; }
.batch-heading > span:last-child { color: var(--muted); }
.task-row { display: flex; align-items: center; gap: 20px; padding: 19px 14px; border-bottom: 1px solid var(--line); }
.task-identity { display: flex; flex-direction: column; gap: 7px; min-width: 100px; font-size: 12px; }
.task-identity > span { color: var(--muted); font-size: 11px; }
.task-detail { display: flex; flex-direction: column; flex: 1; gap: 6px; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.task-detail small { color: var(--muted); font-size: 11px; }
.task-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dialog-note { font-size: 13px; color: var(--muted); line-height: 1.7; margin-top: 0; }
.import-input { margin: 17px 0; }
.image-url { display: flex; gap: 10px; margin-top: 20px; }
.evidence-image { display: block; width: 100%; margin-bottom: 20px; }
.resolution-form { margin-top: 20px; }
.resolution-form :deep(.el-select) { width: 100%; }
@media (max-width: 1380px) { .workspace-grid { grid-template-columns: 165px minmax(330px, 1fr) 264px; gap: 14px; } .distribution-panel { padding: 20px 15px; } .article-editor :deep(.tiptap) { padding-left: 25px; padding-right: 25px; } }
@media (max-width: 1100px) { .workspace-grid { grid-template-columns: minmax(320px, 1fr) 270px; } .draft-rail { grid-column: 1 / -1; padding: 0; } .draft-list { display: flex; max-height: 130px; overflow-x: auto; margin-bottom: 10px; } .draft-row { min-width: 200px; width: 240px; border-bottom: 0; } .rail-heading { margin-bottom: 9px; } .task-row { gap: 13px; flex-wrap: wrap; } .task-detail { min-width: 160px; } }
@media (max-width: 760px) { .workspace-header { align-items: flex-start; } h1 { font-size: 26px; } .workspace-grid { display: flex; flex-direction: column; } .draft-rail, .writing-panel, .distribution-panel { width: 100%; box-sizing: border-box; } .document-title { padding-left: 22px; padding-right: 22px; } .document-title :deep(.el-input__inner) { font-size: 22px; } .document-cover { padding-left: 22px; padding-right: 22px; } .writing-topbar { padding: 12px 15px; } .history-panel { padding: 20px 16px; } .task-row { padding: 15px 0; } .task-actions { width: 100%; } .common-tags { padding: 15px 20px; } }
/* 极窄窗口仍支持现有侧栏展开，操作按钮和任务说明按可用宽度换行。 */
@media (max-width: 520px) {
  .workspace-header { flex-direction: column; align-items: stretch; gap: 14px; }
  .workspace-header > .el-button { align-self: flex-start; }
  .writing-topbar { flex-wrap: wrap; padding: 12px 10px; }
  .writing-actions { flex-wrap: wrap; width: 100%; }
  .writing-actions :deep(.el-button + .el-button) { margin-left: 0; }
  .article-editor :deep(.tiptap) { padding-left: 15px; padding-right: 15px; }
  .account-option { flex-wrap: wrap; }
  .account-option :deep(.el-checkbox) { max-width: 100%; }
  .common-tags { flex-direction: column; align-items: stretch; gap: 8px; padding: 15px 12px; }
  .history-panel { padding: 20px 10px; }
  .history-heading { flex-direction: column; align-items: flex-start; gap: 12px; }
  .batch-heading { flex-wrap: wrap; }
  .task-identity { min-width: 0; }
  .task-detail { min-width: 0; flex-basis: 100%; }
}
</style>
