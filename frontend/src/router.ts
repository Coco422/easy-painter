import { createRouter, createWebHistory } from 'vue-router'

import { isLoggedIn } from '@/lib/auth'

const routes = [
  { path: '/', component: () => import('@/pages/InspirationPage.vue') },
  { path: '/create', component: () => import('@/pages/CreatePage.vue') },
  { path: '/login', component: () => import('@/pages/LoginPage.vue') },
  { path: '/profile', component: () => import('@/pages/ProfilePage.vue') },
  {
    path: '/gallery',
    component: () => import('@/pages/GalleryPage.vue'),
    beforeEnter: () => {
      if (!isLoggedIn()) return '/login'
    },
  },
  { path: '/gallery/:username', component: () => import('@/pages/PublicGalleryPage.vue') },
  { path: '/admin', component: () => import('@/pages/admin/AdminPage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
