import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'

import { isLoggedIn } from '@/lib/auth'

const routes = [
  { path: '/mcp', component: () => import('@/pages/AgentConnectPage.vue') },
  { path: '/mcp/authorize', component: () => import('@/pages/AgentAuthorizePage.vue') },
  { path: '/mcp/callback', component: () => import('@/pages/AgentTestPage.vue') },
  { path: '/', component: () => import('@/pages/InspirationPage.vue') },
  { path: '/create', component: () => import('@/pages/CreatePage.vue') },
  { path: '/canvas/:id?', component: () => import('@/pages/CanvasPage.vue'), beforeEnter: (to: RouteLocationNormalized) => {
    if (!isLoggedIn()) return { path: '/login', query: { redirect: to.fullPath } }
  } },
  { path: '/login', component: () => import('@/pages/LoginPage.vue') },
  { path: '/profile', component: () => import('@/pages/ProfilePage.vue') },
  { path: '/recharge/:result(return)?', component: () => import('@/pages/RechargePage.vue'), beforeEnter: (to: RouteLocationNormalized) => {
    if (!isLoggedIn()) return { path: '/login', query: { redirect: to.fullPath } }
  } },
  {
    path: '/gallery',
    component: () => import('@/pages/ArtworkLibraryPage.vue'),
    props: { mode: 'gallery' },
    beforeEnter: () => {
      if (!isLoggedIn()) return '/login'
    },
  },
  { path: '/gallery/:username', component: () => import('@/pages/ArtworkLibraryPage.vue'), props: { mode: 'gallery' } },
  { path: '/history', component: () => import('@/pages/ArtworkLibraryPage.vue'), props: { mode: 'history' }, beforeEnter: () => { if (!isLoggedIn()) return '/login' } },
  { path: '/favorites', component: () => import('@/pages/ArtworkLibraryPage.vue'), props: { mode: 'favorites' }, beforeEnter: () => { if (!isLoggedIn()) return '/login' } },
  { path: '/admin', component: () => import('@/pages/admin/AdminPage.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
