import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppShell } from '../components/AppShell';
import { routeManifest } from '../router';

describe('UI route coverage', () => {
  it('declares all 14 approved pages without duplicate paths', () => {
    expect(routeManifest).toHaveLength(14);
    expect(new Set(routeManifest.map((route) => route.path)).size).toBe(14);
    expect(routeManifest.map((route) => route.title)).toEqual(expect.arrayContaining(['问数据 - 空状态', '数据源列表', '语义模型编辑器', '用户角色与审计']));
  });

  it('keeps exactly six top-level workspace navigation entries', () => {
    const router = createMemoryRouter([{ element: <AppShell/>, children: [{ path: '/', element: <div>首页</div> }] }], { initialEntries: ['/'] });
    render(<RouterProvider router={router}/>);
    const nav = screen.getByRole('navigation', { name: '一级导航' });
    expect(nav.querySelectorAll('a')).toHaveLength(6);
    ['问数据', '数据源', '语义模型', '答案库', '看板', '评测中心'].forEach((label) => expect(nav).toHaveTextContent(label));
    expect(nav).not.toHaveTextContent('系统设置');
  });
});
