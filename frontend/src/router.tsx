import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { LoginPage } from './pages/LoginPage';
import { AskPage } from './pages/AskPage';
import { DatasourcesPage } from './pages/DatasourcesPage';
import { DatasourceDetailPage } from './pages/DatasourceDetailPage';
import { SemanticModelsPage } from './pages/SemanticModelsPage';
import { SemanticEditorPage } from './pages/SemanticEditorPage';
import { LibraryPage, DashboardDetailPage, EvaluationDetailPage } from './pages/SecondaryPages';

export const routeManifest = [
  { path: '/login', title: '登录页' },
  { path: '/', title: '问数据 - 空状态' },
  { path: '/ask/results', title: '问数据 - 分析结果' },
  { path: '/datasources', title: '数据源列表' },
  { path: '/datasources/:id', title: '数据源详情与 Schema 管理' },
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
  { path: '/login', element: <LoginPage /> },
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <AskPage /> },
      { path: '/ask/results', element: <AskPage results /> },
      { path: '/datasources', element: <DatasourcesPage /> },
      { path: '/datasources/:id', element: <DatasourceDetailPage /> },
      { path: '/semantic-models', element: <SemanticModelsPage /> },
      { path: '/semantic-models/:id', element: <SemanticEditorPage /> },
      { path: '/answers', element: <LibraryPage kind="answers" /> },
      { path: '/dashboards', element: <LibraryPage kind="dashboards" /> },
      { path: '/dashboards/:id', element: <DashboardDetailPage /> },
      { path: '/evaluation', element: <LibraryPage kind="evaluation" /> },
      { path: '/evaluation/:id', element: <EvaluationDetailPage /> },
      { path: '/settings/models', element: <LibraryPage kind="settings" /> },
      { path: '/settings/security', element: <LibraryPage kind="security" /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
]);
