<template>
  <div class="account-management">
    <div class="page-header">
      <h1>账号管理</h1>
    </div>
    
    <div class="account-tabs">
      <el-tabs v-model="activeTab" class="account-tabs-nav">
        <el-tab-pane label="全部" name="all">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(null)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            
            <div v-if="filteredAccounts.length > 0" class="account-list">
              <el-table :data="filteredAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" :disabled="Boolean(ACCOUNT_UNAVAILABLE_REASONS[scope.row.type])" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            
            <div v-else class="empty-data">
              <el-empty description="暂无账号数据" />
            </div>
          </div>
        </el-tab-pane>
        
        <el-tab-pane label="快手" name="kuaishou">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(4)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            
            <div v-if="filteredKuaishouAccounts.length > 0" class="account-list">
              <el-table :data="filteredKuaishouAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            
            <div v-else class="empty-data">
              <el-empty description="暂无快手账号数据" />
            </div>
          </div>
        </el-tab-pane>
        
        <el-tab-pane label="抖音" name="douyin">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(3)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            
            <div v-if="filteredDouyinAccounts.length > 0" class="account-list">
              <el-table :data="filteredDouyinAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            
            <div v-else class="empty-data">
              <el-empty description="暂无抖音账号数据" />
            </div>
          </div>
        </el-tab-pane>
        
        <el-tab-pane label="视频号" name="channels">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(2)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            
            <div v-if="filteredChannelsAccounts.length > 0" class="account-list">
              <el-table :data="filteredChannelsAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            
            <div v-else class="empty-data">
              <el-empty description="暂无视频号账号数据" />
            </div>
          </div>
        </el-tab-pane>
        
        <el-tab-pane label="小红书" name="xiaohongshu">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(1)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            
            <div v-if="filteredXiaohongshuAccounts.length > 0" class="account-list">
              <el-table :data="filteredXiaohongshuAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            
            <div v-else class="empty-data">
              <el-empty description="暂无小红书账号数据" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="百家号" name="baijiahao">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(5)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>

            <div v-if="filteredBaijiahaoAccounts.length > 0" class="account-list">
              <el-table :data="filteredBaijiahaoAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="empty-data">
              <el-empty description="暂无百家号账号数据" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="B站" name="bilibili">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(6)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>

            <div v-if="filteredBilibiliAccounts.length > 0" class="account-list">
              <el-table :data="filteredBilibiliAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="empty-data">
              <el-empty description="暂无B站账号数据" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="今日头条" name="toutiao">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(7)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>

            <div v-if="filteredToutiaoAccounts.length > 0" class="account-list">
              <el-table :data="filteredToutiaoAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="empty-data">
              <el-empty description="暂无今日头条账号数据" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="搜狐" name="sohu">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(8)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>

            <div v-if="filteredSohuAccounts.length > 0" class="account-list">
              <el-table :data="filteredSohuAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="empty-data">
              <el-empty description="暂无搜狐账号数据" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="知乎" name="zhihu">
          <div class="account-list-container">
            <div class="account-search">
              <el-input
                v-model="searchKeyword"
                placeholder="输入名称或账号搜索"
                prefix-icon="Search"
                clearable
                @clear="handleSearch"
                @input="handleSearch"
              />
              <div class="action-buttons">
                <el-button type="primary" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" @click="fetchAccounts(9)" :loading="false">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>

            <div v-if="filteredZhihuAccounts.length > 0" class="account-list">
              <el-table :data="filteredZhihuAccounts" style="width: 100%">
                <el-table-column label="头像" width="80">
                  <template #default="scope">
                    <el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" />
                  </template>
                </el-table-column>
                <el-table-column prop="name" label="名称" width="180" />
                <el-table-column prop="platform" label="平台">
                  <template #default="scope">
                    <el-tag
                      :type="getPlatformTagType(scope.row.platform)"
                      effect="plain"
                    >
                      {{ scope.row.platform }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="status" label="状态">
                  <template #default="scope">
                    <el-tag
                      :type="getStatusTagType(scope.row.status)"
                      effect="plain"
                      :class="{'clickable-status': isStatusClickable(scope.row.status)}"
                      @click="handleStatusClick(scope.row)"
                    >
                      <el-icon :class="scope.row.status === '验证中' ? 'is-loading' : ''" v-if="scope.row.status === '验证中'">
                        <Loading />
                      </el-icon>
                      {{ scope.row.status }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作">
                  <template #default="scope">
                    <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                    <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                    <el-button size="small" type="info" :icon="Upload" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                    <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <div v-else class="empty-data">
              <el-empty description="暂无知乎账号数据" />
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane v-for="platform in articleAccountPlatforms" :key="platform.key" :label="platform.notice ? `${platform.label}（待接入）` : platform.label" :name="platform.key">
          <div class="account-list-container">
            <el-alert v-if="platform.notice" :title="platform.notice" type="info" :closable="false" show-icon />
            <div class="account-search">
              <el-input v-model="searchKeyword" placeholder="输入名称或账号搜索" prefix-icon="Search" clearable @clear="handleSearch" @input="handleSearch" />
              <div class="action-buttons">
                <el-button type="primary" :disabled="Boolean(platform.notice)" @click="handleAddAccount">添加账号</el-button>
                <el-button type="info" :disabled="Boolean(platform.notice)" @click="fetchAccounts(platform.type)">
                  <el-icon :class="{ 'is-loading': appStore.isAccountRefreshing }"><Refresh /></el-icon>
                  <span v-if="appStore.isAccountRefreshing">刷新中</span>
                </el-button>
              </div>
            </div>
            <el-table v-if="getFilteredPlatformAccounts(platform.label).length" :data="getFilteredPlatformAccounts(platform.label)" class="account-list" style="width: 100%">
              <el-table-column label="头像" width="80">
                <template #default="scope"><el-avatar :src="getDefaultAvatar(scope.row.name)" :size="40" /></template>
              </el-table-column>
              <el-table-column prop="name" label="名称" width="180" />
              <el-table-column prop="platform" label="平台">
                <template #default="scope"><el-tag :type="getPlatformTagType(scope.row.platform)" effect="plain">{{ scope.row.platform }}</el-tag></template>
              </el-table-column>
              <el-table-column prop="status" label="状态">
                <template #default="scope">
                  <el-tag :type="getStatusTagType(scope.row.status)" effect="plain" :class="{ 'clickable-status': isStatusClickable(scope.row.status) }" @click="handleStatusClick(scope.row)">
                    <el-icon v-if="scope.row.status === '验证中'" class="is-loading"><Loading /></el-icon>
                    {{ scope.row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作">
                <template #default="scope">
                  <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
                  <el-button size="small" type="primary" :icon="Download" @click="handleDownloadCookie(scope.row)">下载Cookie</el-button>
                  <el-button size="small" type="info" :icon="Upload" :disabled="Boolean(platform.notice)" @click="handleUploadCookie(scope.row)">上传Cookie</el-button>
                  <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else :description="`暂无${platform.label}账号数据`" class="empty-data" />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
    
    <!-- 添加/编辑账号对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogType === 'add' ? '添加账号' : '编辑账号'"
      width="min(500px, calc(100vw - 24px))"
      :close-on-click-modal="false"
      :close-on-press-escape="!sseConnecting"
      :show-close="!sseConnecting"
    >
      <el-form :model="accountForm" label-width="80px" :rules="rules" ref="accountFormRef">
        <el-form-item label="平台" prop="platform">
          <el-select 
            v-model="accountForm.platform" 
            placeholder="请选择平台" 
            style="width: 100%"
            :disabled="dialogType === 'edit' || sseConnecting"
          >
            <el-option v-for="(label, type) in PLATFORM_TYPES" :key="type" :label="ACCOUNT_UNAVAILABLE_REASONS[type] ? `${label}（待接入）` : label" :value="label" :disabled="Boolean(ACCOUNT_UNAVAILABLE_REASONS[type])" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input 
            v-model="accountForm.name" 
            placeholder="请输入账号名称" 
            :disabled="sseConnecting"
          />
        </el-form-item>
        
        <el-alert v-if="accountFormNotice" :title="accountFormNotice" type="info" :closable="false" show-icon />

        <!-- 二维码显示区域 -->
        <div v-if="sseConnecting" class="qrcode-container">
          <div v-if="qrCodeData && !loginStatus" class="qrcode-wrapper">
            <p class="qrcode-tip">请使用对应平台APP扫描二维码登录</p>
            <img :src="qrCodeData" alt="登录二维码" class="qrcode-image" />
          </div>
          <div v-else-if="isManualLogin && !loginStatus" class="loading-wrapper">
            <el-icon><Monitor /></el-icon>
            <span>已打开浏览器，请在浏览器窗口中手动登录</span>
          </div>
          <div v-else-if="!qrCodeData && !loginStatus && !isManualLogin" class="loading-wrapper">
            <el-icon class="is-loading"><Refresh /></el-icon>
            <span>请求中...</span>
          </div>
          <div v-else-if="loginStatus === '200'" class="success-wrapper">
            <el-icon><CircleCheckFilled /></el-icon>
            <span>添加成功</span>
          </div>
          <div v-else-if="loginStatus === '500'" class="error-wrapper">
            <el-icon><CircleCloseFilled /></el-icon>
            <span>添加失败，请稍后再试</span>
          </div>
        </div>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button v-if="dialogType === 'add'" :loading="importingCookie" :disabled="sseConnecting || Boolean(accountFormNotice)" @click="importAccountCookie">导入 Cookie</el-button>
          <el-button @click="handleCancel">取消</el-button>
          <el-button 
            type="primary" 
            @click="submitAccountForm" 
            :loading="sseConnecting" 
            :disabled="sseConnecting || importingCookie || (dialogType === 'add' && Boolean(accountFormNotice))"
          >
            {{ sseConnecting ? '请求中' : '确认' }}
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { Refresh, CircleCheckFilled, CircleCloseFilled, Download, Upload, Loading, Monitor } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi } from '@/api/account'
import { useAccountStore, PLATFORM_TYPES, ACCOUNT_UNAVAILABLE_REASONS } from '@/stores/account'
import { useAppStore } from '@/stores/app'
import { http } from '@/utils/request'

// 获取账号状态管理
const accountStore = useAccountStore()
// 获取应用状态管理
const appStore = useAppStore()

// 当前激活的标签页
const activeTab = ref('all')
const importingCookie = ref(false)

// Tab name -> 后端 platform type
const TAB_PLATFORM_TYPE = {
  kuaishou: 4,
  douyin: 3,
  channels: 2,
  xiaohongshu: 1,
  baijiahao: 5,
  bilibili: 6,
  toutiao: 7,
  sohu: 8,
  zhihu: 9,
  weibo: 10,
  qiehao: 11,
  yidian: 12,
  dayu: 13,
  netease: 14,
  acfun: 15,
  kuaichuan: 16,
  xueqiu: 17,
  jingdong: 18,
  douban: 19,
  csdn: 20,
  jianshu: 21,
  chejiahao: 22,
  yiche: 23,
  dongchedi: 24
}

const PLATFORM_LABEL_BY_TYPE = PLATFORM_TYPES
const TAB_PLATFORM_LABEL = Object.fromEntries(
  Object.entries(TAB_PLATFORM_TYPE).map(([key, type]) => [key, PLATFORM_TYPES[type]])
)
const articleAccountPlatforms = Object.entries(TAB_PLATFORM_TYPE)
  .filter(([, type]) => type >= 10)
  .map(([key, type]) => ({ key, type, label: PLATFORM_TYPES[type], notice: ACCOUNT_UNAVAILABLE_REASONS[type] }))

const getPlatformTypeByLabel = (platformLabel) => {
  const entry = Object.entries(PLATFORM_TYPES).find(([, name]) => name === platformLabel)
  return entry ? Number(entry[0]) : null
}

// 搜索关键词
const searchKeyword = ref('')

// 获取账号数据（快速，不验证，使用数据库中已有状态）
const fetchAccountsQuick = async () => {
  try {
    const res = await accountApi.getAccounts()
    if (res.code === 200 && res.data) {
      accountStore.setAccounts(res.data)
    }
  } catch (error) {
    console.error('快速获取账号数据失败:', error)
  }
}

// 获取账号数据（带验证，仅手动刷新时调用）
// platformType: null=全部平台，数字=仅该平台
const fetchAccounts = async (platformType = null) => {
  if (appStore.isAccountRefreshing) return

  appStore.setAccountRefreshing(true)

  const platformLabel = platformType == null ? '全部' : (PLATFORM_LABEL_BY_TYPE[platformType] || '平台')

  try {
    const res = await accountApi.getValidAccounts(platformType)
    if (res.code === 200 && res.data) {
      if (platformType != null) {
        accountStore.mergeAccounts(res.data)
      } else {
        accountStore.setAccounts(res.data)
      }
      ElMessage.success(`${platformLabel}账号刷新成功`)
      if (appStore.isFirstTimeAccountManagement) {
        appStore.setAccountManagementVisited()
      }
    } else {
      ElMessage.error('获取账号数据失败')
    }
  } catch (error) {
    console.error('获取账号数据失败:', error)
    ElMessage.error('获取账号数据失败')
  } finally {
    appStore.setAccountRefreshing(false)
  }
}

// 页面加载时仅拉取账号列表，不自动验证 Cookie
onMounted(() => {
  fetchAccountsQuick()
})

// 获取平台标签类型
const getPlatformTagType = (platform) => {
  const typeMap = {
    '快手': 'success',
    '抖音': 'danger',
    '视频号': 'warning',
    '小红书': 'info',
    '百家号': '',
    'B站': 'danger',
    '今日头条': 'warning',
    '搜狐': 'success',
    '知乎': 'info'
  }
  return typeMap[platform] || 'info'
}

// 判断状态是否可点击（异常状态可点击）
const isStatusClickable = (status) => {
  return status === '异常'; // 只有异常状态可点击，验证中不可点击
}

// 获取状态标签类型
const getStatusTagType = (status) => {
  if (status === '验证中' || status === '待接入') {
    return 'info'; // 验证中使用灰色
  } else if (status === '正常') {
    return 'success'; // 正常使用绿色
  } else {
    return 'danger'; // 无效使用红色
  }
}

// 处理状态点击事件
const handleStatusClick = (row) => {
  if (isStatusClickable(row.status)) {
    // 触发重新登录流程
    handleReLogin(row)
  }
}

// 过滤后的账号列表
const filteredAccounts = computed(() => {
  if (!searchKeyword.value) return accountStore.accounts
  return accountStore.accounts.filter(account =>
    account.name.includes(searchKeyword.value)
  )
})

// 按平台过滤的账号列表
const filteredKuaishouAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '快手')
})

const filteredDouyinAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '抖音')
})

const filteredChannelsAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '视频号')
})

const filteredXiaohongshuAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '小红书')
})

const filteredBaijiahaoAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '百家号')
})

const filteredBilibiliAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === 'B站')
})

const filteredToutiaoAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '今日头条')
})

const filteredSohuAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '搜狐')
})

const filteredZhihuAccounts = computed(() => {
  return filteredAccounts.value.filter(account => account.platform === '知乎')
})

// 新增平台沿用账号列表筛选，不开放未实现的消息或统计能力。
const getFilteredPlatformAccounts = (label) => filteredAccounts.value.filter(account => account.platform === label)

// 搜索处理
const handleSearch = () => {
  // 搜索逻辑已通过计算属性实现
}

// 对话框相关
const dialogVisible = ref(false)
const dialogType = ref('add') // 'add' 或 'edit'
const accountFormRef = ref(null)

// 账号表单
const accountForm = reactive({
  id: null,
  name: '',
  platform: '',
  status: '正常'
})

const accountFormNotice = computed(() => ACCOUNT_UNAVAILABLE_REASONS[getPlatformTypeByLabel(accountForm.platform)] || '')

// 表单验证规则
const rules = {
  platform: [{ required: true, message: '请选择平台', trigger: 'change' }],
  name: [{ required: true, message: '请输入账号名称', trigger: 'blur' }]
}

// SSE连接状态
const sseConnecting = ref(false)
const qrCodeData = ref('')
const loginStatus = ref('')
const isManualLogin = ref(false)

// 添加账号
const handleAddAccount = () => {
  // 清理可能残留的旧登录连接，避免旧连接后续推送的消息干扰新会话
  closeSSEConnection()
  dialogType.value = 'add'
  Object.assign(accountForm, {
    id: null,
    name: '',
    platform: TAB_PLATFORM_LABEL[activeTab.value] || '',
    status: '正常'
  })
  // 重置SSE状态
  sseConnecting.value = false
  qrCodeData.value = ''
  loginStatus.value = ''
  dialogVisible.value = true
}

// 编辑账号
const handleEdit = (row) => {
  dialogType.value = 'edit'
  Object.assign(accountForm, {
    id: row.id,
    name: row.name,
    platform: row.platform,
    status: row.status
  })
  dialogVisible.value = true
}

// 删除账号
const handleDelete = (row) => {
  ElMessageBox.confirm(
    `确定要删除账号 ${row.name} 吗？`,
    '警告',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }
  )
    .then(async () => {
      try {
        // 调用API删除账号
        const response = await accountApi.deleteAccount(row.id)

        if (response.code === 200) {
          // 从状态管理中删除账号
          accountStore.deleteAccount(row.id)
          ElMessage({
            type: 'success',
            message: '删除成功',
          })
        } else {
          ElMessage.error(response.msg || '删除失败')
        }
      } catch (error) {
        console.error('删除账号失败:', error)
        ElMessage.error('删除账号失败')
      }
    })
    .catch(() => {
      // 取消删除
    })
}

// 下载Cookie文件
const handleDownloadCookie = (row) => {
  // 从后端获取Cookie文件
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'
  const downloadUrl = `${baseUrl}/downloadCookie?filePath=${encodeURIComponent(row.filePath)}`

  // 创建一个隐藏的链接来触发下载
  const link = document.createElement('a')
  link.href = downloadUrl
  link.download = `${row.name}_cookie.json`
  link.target = '_blank'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// 首次导入也由后端验证会话与发布权限，前端不会据文件格式推定已登录。
const importAccountCookie = async () => {
  if (importingCookie.value || !(await accountFormRef.value.validate().catch(() => false))) return
  const platform = getPlatformTypeByLabel(accountForm.platform)
  const name = accountForm.name.trim()
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    const formData = new FormData()
    formData.append('file', file)
    formData.append('platform', platform)
    formData.append('name', name)
    importingCookie.value = true
    try {
      await http.upload('/importCookie', formData)
      ElMessage.success('账号 Cookie 已导入并通过验证')
      dialogVisible.value = false
      await fetchAccountsQuick()
    } catch { /* 请求层展示后端验证原因，保留账号表单供重新导入。 */ }
    finally { importingCookie.value = false }
  }
  input.click()
}

// 上传Cookie文件
const handleUploadCookie = (row) => {
  const notice = ACCOUNT_UNAVAILABLE_REASONS[getPlatformTypeByLabel(row.platform)]
  if (notice) {
    ElMessage.info(notice)
    return
  }
  // 创建一个隐藏的文件输入框
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.style.display = 'none'
  document.body.appendChild(input)

  input.onchange = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    // 检查文件类型
    if (!file.name.endsWith('.json')) {
      ElMessage.error('请选择JSON格式的Cookie文件')
      document.body.removeChild(input)
      return
    }

    try {
      // 创建FormData对象
      const formData = new FormData()
      formData.append('file', file)
      formData.append('id', row.id)
      formData.append('platform', getPlatformTypeByLabel(row.platform))

      // 使用统一的http封装发送上传请求
      const result = await http.upload('/uploadCookie', formData)

      ElMessage.success('Cookie文件上传成功')
      fetchAccounts(getPlatformTypeByLabel(row.platform))
    } catch (error) {
      ElMessage.error('Cookie文件上传失败')
    } finally {
      document.body.removeChild(input)
    }
  }

  input.click()
}

// 重新登录账号
const handleReLogin = (row) => {
  // 设置表单信息
  dialogType.value = 'edit'
  Object.assign(accountForm, {
    id: row.id,
    name: row.name,
    platform: row.platform,
    status: row.status
  })

  // 重置SSE状态
  sseConnecting.value = false
  qrCodeData.value = ''
  loginStatus.value = ''

  // 显示对话框
  dialogVisible.value = true

  // 立即开始登录流程
  setTimeout(() => {
    connectSSE(row.platform, row.name)
  }, 300)
}

// 获取默认头像
const getDefaultAvatar = (name) => {
  // 使用简单的默认头像，可以基于用户名生成不同的颜色
  return `https://ui-avatars.com/api/?name=${encodeURIComponent(name)}&background=random`
}

// SSE事件源对象
let eventSource = null
// 等待首条后端消息的防呆定时器
let qrWaitTimer = null

// 清理防呆定时器
const clearQrWaitTimer = () => {
  if (qrWaitTimer) {
    clearTimeout(qrWaitTimer)
    qrWaitTimer = null
  }
}

// 取消当前登录并关闭对话框
const handleCancel = () => {
  const wasConnecting = sseConnecting.value
  closeSSEConnection()
  sseConnecting.value = false
  qrCodeData.value = ''
  loginStatus.value = ''
  dialogVisible.value = false
  if (wasConnecting) {
    ElMessage.info('已取消本次登录')
  }
}

// 关闭SSE连接
const closeSSEConnection = () => {
  clearQrWaitTimer()
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  isManualLogin.value = false
}

// 建立SSE连接
const connectSSE = (platform, name) => {
  const notice = ACCOUNT_UNAVAILABLE_REASONS[getPlatformTypeByLabel(platform)]
  if (notice) {
    ElMessage.info(notice)
    return
  }
  // 关闭可能存在的连接
  closeSSEConnection()

  // 设置连接状态
  sseConnecting.value = true
  qrCodeData.value = ''
  loginStatus.value = ''

  // 防呆：长时间收不到后端任何消息时自动结束，避免一直停留在"请求中"
  qrWaitTimer = setTimeout(() => {
    if (sseConnecting.value && !qrCodeData.value && !loginStatus.value && !isManualLogin.value) {
      ElMessage.error('登录请求超时，请确认后端服务正常后重试')
      closeSSEConnection()
      sseConnecting.value = false
    }
  }, 180000)

  // 获取平台类型编号
  const type = getPlatformTypeByLabel(platform)
  if (type == null) {
    closeSSEConnection()
    sseConnecting.value = false
    ElMessage.error('请选择支持的账号平台')
    return
  }

  // 创建SSE连接
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5409'
  // Vite 开发代理会缓冲 SSE 长连接，登录流直接连接后端端口
  const sseBaseUrl = baseUrl.startsWith('/') ? 'http://localhost:5409' : baseUrl
  const url = `${sseBaseUrl}/login?type=${type}&id=${encodeURIComponent(name)}`

  eventSource = new EventSource(url)

  // 监听消息
  eventSource.onmessage = (event) => {
    const data = event.data

    // 收到首条消息即说明链路正常，解除防呆超时
    clearQrWaitTimer()

    // 无界面服务器通过已登录会话文件完成添加，避免继续等待无法展示的登录窗口。
    if (data === 'IMPORT_COOKIE') {
      closeSSEConnection()
      sseConnecting.value = false
      ElMessage.warning('当前服务器无法打开登录窗口，请使用导入 Cookie 添加账号')
      return
    }

    // 手动登录模式（百家号、B站等）
    if (data === 'MANUAL_LOGIN') {
      qrCodeData.value = ''
      loginStatus.value = ''
      isManualLogin.value = true
      // 提示信息根据平台区分
      const platform = accountForm.platform
      if (platform === 'B站') {
        ElMessage({ message: '已打开终端窗口，请在终端中扫码登录Bilibili，登录完成后会自动继续', type: 'info', duration: 10000 })
      } else if (platform === '今日头条') {
        ElMessage({ message: '已打开浏览器，请使用今日头条APP扫码登录，登录完成后系统将自动继续', type: 'info', duration: 10000 })
      } else if (platform === '搜狐') {
        ElMessage({ message: '已打开浏览器，请在搜狐号登录页完成登录，登录完成后系统将自动继续', type: 'info', duration: 10000 })
      } else if (platform === '知乎') {
        ElMessage({ message: '已打开浏览器，请在知乎登录页完成登录，登录完成后系统将自动继续', type: 'info', duration: 10000 })
      } else {
        ElMessage({ message: '已打开浏览器，请在浏览器窗口中手动登录，登录完成后系统将自动继续', type: 'info', duration: 10000 })
      }
      return
    }

    // 视频号二维码可能是完整图片地址，而不是 base64 字符串
    const isImageUrl = data.startsWith('http://') || data.startsWith('https://')
    if (!qrCodeData.value && (data.startsWith('data:image') || isImageUrl || data.length > 100)) {
      try {
        if (data.startsWith('data:image')) {
          qrCodeData.value = data
        } else if (isImageUrl) {
          qrCodeData.value = data
        } else {
          qrCodeData.value = `data:image/png;base64,${data}`
        }
      } catch (error) {
        // 处理二维码数据出错
      }
    }
    // 如果收到状态码
    else if (data === '200' || data === '500') {
      loginStatus.value = data

      // 如果登录成功
      if (data === '200') {
        setTimeout(() => {
          // 关闭连接
          closeSSEConnection()

          // 1秒后关闭对话框并开始刷新
          setTimeout(() => {
            dialogVisible.value = false
            sseConnecting.value = false

            // 根据是否是重新登录显示不同提示
            ElMessage.success(dialogType.value === 'edit' ? '重新登录成功' : '账号添加成功')

            // 登录流程内已校验当前账号 cookie，这里只刷新列表，不再全量检测
            fetchAccountsQuick().then(() => {
              ElMessage.success('账号信息已更新')
            })
          }, 1000)
        }, 1000)
      } else {
        // 登录失败，关闭连接
        closeSSEConnection()

        // 2秒后重置状态，允许重试
        setTimeout(() => {
          sseConnecting.value = false
          qrCodeData.value = ''
          loginStatus.value = ''
        }, 2000)
      }
    }
  }

  // 监听错误
  eventSource.onerror = (error) => {
    console.error('SSE连接错误:', error)
    ElMessage.error('连接服务器失败，请稍后再试')
    closeSSEConnection()
    sseConnecting.value = false
  }
}

// 提交账号表单
const submitAccountForm = () => {
  accountFormRef.value.validate(async (valid) => {
    if (valid) {
      if (dialogType.value === 'add') {
        // 建立SSE连接
        connectSSE(accountForm.platform, accountForm.name)
      } else {
        // 编辑账号逻辑
        try {
          // 将平台名称转换为类型数字
          const type = getPlatformTypeByLabel(accountForm.platform)
          if (type == null) {
            ElMessage.error('请选择支持的账号平台')
            return
          }

          const res = await accountApi.updateAccount({
            id: accountForm.id,
            type: type,
            userName: accountForm.name
          })
          if (res.code === 200) {
            // 更新状态管理中的账号
            const updatedAccount = {
              id: accountForm.id,
              name: accountForm.name,
              platform: accountForm.platform,
              status: accountForm.status // Keep the existing status
            };
            accountStore.updateAccount(accountForm.id, updatedAccount)
            ElMessage.success('更新成功')
            dialogVisible.value = false
            fetchAccounts(getPlatformTypeByLabel(accountForm.platform))
          } else {
            ElMessage.error(res.msg || '更新账号失败')
          }
        } catch (error) {
          console.error('更新账号失败:', error)
          ElMessage.error('更新账号失败')
        }
      }
    } else {
      return false
    }
  })
}

// 组件卸载前关闭SSE连接
onBeforeUnmount(() => {
  closeSSEConnection()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

@keyframes rotate {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.account-management {
  .page-header {
    margin-bottom: 20px;
    
    h1 {
      font-size: 24px;
      color: $text-primary;
      margin: 0;
    }
  }
  
  .account-tabs {
    background-color: #fff;
    border-radius: 4px;
    box-shadow: $box-shadow-light;
    
    .account-tabs-nav {
      padding: 20px;
    }
  }
  
  .account-list-container {
    .account-search {
      display: flex;
      justify-content: space-between;
      margin-bottom: 20px;
      
      .el-input {
        width: 300px;
      }
      
      .action-buttons {
        display: flex;
        gap: 10px;
        
        .el-icon.is-loading {
          animation: rotate 1s linear infinite;
        }
      }
    }
    
    .account-list {
      margin-bottom: 20px;
    }
    
    .empty-data {
      padding: 40px 0;
    }
  }
  
  // 二维码容器样式
  .clickable-status {
    cursor: pointer;
    transition: all 0.3s;

    &:hover {
      transform: scale(1.05);
      box-shadow: 0 0 8px rgba(0, 0, 0, 0.15);
    }
  }

  .qrcode-container {
    margin-top: 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 250px;
    
    .qrcode-wrapper {
      text-align: center;
      
      .qrcode-tip {
        margin-bottom: 15px;
        color: #606266;
      }
      
      .qrcode-image {
        max-width: 200px;
        max-height: 200px;
        border: 1px solid #ebeef5;
        background-color: black;
      }
    }
    
    .loading-wrapper, .success-wrapper, .error-wrapper {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      
      .el-icon {
        font-size: 48px;
        
        &.is-loading {
          animation: rotate 1s linear infinite;
        }
      }
      
      span {
        font-size: 16px;
      }
    }
    
    .success-wrapper .el-icon {
      color: #67c23a;
    }
    
    .error-wrapper .el-icon {
      color: #f56c6c;
    }
  }
}
</style>
