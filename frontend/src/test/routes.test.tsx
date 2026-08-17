import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppShell } from '../components/AppShell';
import { routeManifest } from '../router';

describe('UI route coverage', () => {
  it('declares all 14 approved pages without duplicate paths', () => {
    expect(routeManifest).toHaveLength(14);
    expect(new Set(routeManifest.map((route) => route.path)).size).toBe(14);
    expect(routeManifest).toEqual([
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
    ]);
  });

  it('keeps exactly six top-level workspace navigation entries', () => {
    const router = createMemoryRouter([{ element: <AppShell/>, children: [{ path: '/', element: <div>首页</div> }] }], { initialEntries: ['/'] });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><RouterProvider router={router}/></QueryClientProvider>);
    const nav = screen.getByRole('navigation', { name: '一级导航' });
    expect(nav.querySelectorAll('a')).toHaveLength(6);
    ['问数据', '数据源', '语义模型', '答案库', '看板', '评测中心'].forEach((label) => expect(nav).toHaveTextContent(label));
    expect(nav).not.toHaveTextContent('系统设置');
  });
});
