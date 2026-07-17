<script setup>
defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: true },
})
</script>

<template>
  <div class="dashboard-widget">
    <v-card>
      <v-card-title class="text-subtitle-1">
        <v-icon size="small" class="mr-1">mdi-swap-horizontal</v-icon>
        Discord消息转发
      </v-card-title>
      <v-card-text class="text-caption">运行详情请打开插件详情页查看。</v-card-text>
    </v-card>
  </div>
</template>
