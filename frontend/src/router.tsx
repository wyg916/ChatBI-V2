import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { ProtectedRoute } from './auth';

export const routeManifest = [
  { path: '/login', title: '登录页' },
  { path: '/', title: '问数据 - 空状态' },
  { path: '/ask/results', title: '问数据 - 分析结果' },
  { path: '/datasources', title: '数据源列表' },
  { path: '/datasources/:id', title: '数据源详情与 Schema 管理' },
  { path: '/datasources/:id/workspace', title: '数据工作台' },
  { path: '/semantic-models', title: '语义模型列表' },
  { path: '/semantic-models/:id', title: '语义模型编辑器' },
  { path: '/answers', title: '答案库' },
  { path: '/dashboards', title: '看板列表' },
  { path: '/dashboards/:id', title: '经营看板详情' },
  { path: '/evaluation', title: '评测中心总览' },
  { path: '/evaluation/:id', title: '评测用例详情' },
  { path: '/settings/models', title: '系统设置与模型服务' },
  { path: '/settings/security', title: '用户角色与审计' },
] as const;

export const router = createBrowserRouter([
  { path: '/login', lazy: async () => ({ Component: (await import('./pages/LoginPage')).LoginPage }) },
  { path: '/share/:token', lazy: async () => ({ Component: (await import('./pages/SharedConversationPage')).SharedConversationPage }) },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppShell />,
        children: [
      { path: '/', lazy: async () => ({ Component: (await import('./pages/AskPage')).AskPage }) },
      { path: '/ask/results', lazy: async () => {
        const { AskPage } = await import('./pages/AskPage');
        return { Component: () => <AskPage results /> };
      } },
      { path: '/datasources', lazy: async () => ({ Component: (await import('./pages/DatasourcesPage')).DatasourcesPage }) },
      { path: '/datasources/:id', lazy: async () => ({ Component: (await import('./pages/DatasourceDetailPage')).DatasourceDetailPage }) },
      { path: '/datasources/:id/workspace', lazy: async () => ({ Component: (await import('./pages/DataWorkspacePage')).DataWorkspacePage }) },
      { path: '/semantic-models', lazy: async () => ({ Component: (await import('./pages/SemanticModelsPage')).SemanticModelsPage }) },
      { path: '/semantic-models/:id', lazy: async () => ({ Component: (await import('./pages/SemanticEditorPage')).SemanticEditorPage }) },
      { path: '/answers', lazy: async () => ({ Component: (await import('./pages/AnswerLibraryPage')).AnswerLibraryPage }) },
      { path: '/dashboards', lazy: async () => ({ Component: (await import('./pages/DashboardListPage')).DashboardListPage }) },
      { path: '/dashboards/:id', lazy: async () => ({ Component: (await import('./pages/DashboardDetailPage')).DashboardDetailPage }) },
      { path: '/evaluation', lazy: async () => ({ Component: (await import('./pages/EvaluationOverviewPage')).EvaluationOverviewPage }) },
      { path: '/evaluation/:id', lazy: async () => ({ Component: (await import('./pages/EvaluationDetailPage')).EvaluationDetailPage }) },
      { path: '/settings/models', lazy: async () => ({ Component: (await import('./pages/SettingsModelsPage')).SettingsModelsPage }) },
      { path: '/settings/security', lazy: async () => ({ Component: (await import('./pages/SecurityAuditPage')).SecurityAuditPage }) },
        ],
      },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
