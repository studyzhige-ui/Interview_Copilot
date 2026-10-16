export const workspaces = [
  { label: '今天', to: '/today', paths: ['/today'], tabs: [] },
  { label: '求职', to: '/career-process', paths: ['/career-process', '/career-insights', '/career-calendar', '/artifacts'], tabs: [
    { label: '岗位', to: '/career-process' }, { label: '简历与材料', to: '/artifacts' }, { label: '日程', to: '/career-calendar' }, { label: '统计与 Offer', to: '/career-insights' },
  ] },
  { label: '面试', to: '/mock', paths: ['/mock', '/review', '/analytics'], tabs: [
    { label: '模拟面试', to: '/mock' }, { label: '面试复盘', to: '/review' }, { label: '能力成长', to: '/analytics' },
  ] },
  { label: '资料', to: '/career-profile', paths: ['/career-profile', '/library'], tabs: [
    { label: '个人档案', to: '/career-profile' }, { label: '资料库', to: '/library' },
  ] },
  { label: '协作记录', to: '/history', paths: ['/history', '/activity', '/persistent-tasks'], tabs: [
    { label: '执行动态', to: '/activity' }, { label: '对话搜索', to: '/history' }, { label: '持续任务', to: '/persistent-tasks' },
  ] },
  { label: '设置', to: '/settings/personalization', paths: ['/settings', '/models', '/plugins', '/capabilities', '/me'], tabs: [
    { label: '协作偏好', to: '/settings/personalization' }, { label: '回答模型', to: '/models' },
    { label: '通知', to: '/settings/notifications' },
    { label: '插件与连接', to: '/plugins' }, { label: '账户', to: '/me' },
  ] },
];

export function pathMatches(pathname: string, path: string) {
  return pathname === path || pathname.startsWith(`${path}/`);
}

export function workspaceFor(pathname: string) {
  return workspaces.find((area) => area.paths.some((path) => pathMatches(pathname, path)));
}
