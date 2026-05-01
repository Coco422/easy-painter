import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', component: () => import('@/pages/HomePage.vue') },
  { path: '/login', component: () => import('@/pages/LoginPage.vue') },
  { path: '/gallery/:username', component: () => import('@/pages/PublicGalleryPage.vue') },
  { path: '/admin', component: () => import('@/pages/AdminPage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
