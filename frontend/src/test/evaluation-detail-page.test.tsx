import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { EvaluationDetailPage } from '../pages/EvaluationDetailPage';

function renderDetail(path = '/evaluation/EVAL-00428') {
  render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/evaluation/:id" element={<EvaluationDetailPage />}/></Routes></MemoryRouter>);
}

describe('评测用例详情高保真界面', () => {
  it('展示完整设计结构并明确标识为未执行的 UI 示例', () => {
    renderDetail();
    expect(screen.getByRole('heading', { name: '评测用例详情' })).toBeVisible();
    expect(screen.getByText('UI 演示 · 未执行')).toBeVisible();
    expect(screen.getByText('2026 年 6 月各区域充电收入及环比变化是多少？')).toBeVisible();
    expect(screen.getByText('83.3%')).toBeVisible();
    expect(screen.getByText("'completed'")).toBeVisible();
    expect(screen.getByText("'paid'")).toBeVisible();
    expect(screen.getByText('2 个值差异示例')).toBeVisible();
    expect(screen.getAllByRole('row')).toHaveLength(4);
    expect(screen.getByRole('button', { name: '上一条' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '下一条' })).toBeDisabled();
  });

  it('对尚未接入的写操作给出真实状态提示', async () => {
    const user = userEvent.setup();
    renderDetail('/evaluation/day1-demo');
    await user.click(screen.getByRole('button', { name: '重新运行' }));
    expect(screen.getByRole('status')).toHaveTextContent('重新运行尚未接入 Golden Set 执行 API');
    await user.click(screen.getByRole('button', { name: '创建修复任务' }));
    expect(screen.getByRole('status')).toHaveTextContent('创建修复任务尚未接入 Golden Set 执行 API');
  });
});
