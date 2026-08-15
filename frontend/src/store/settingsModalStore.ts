import { create } from 'zustand';

export type SettingsTabKey =
  | 'general'
  | 'models'
  | 'capabilities'
  | 'personalization'
  | 'voice'
  | 'security';

interface SettingsModalState {
  isOpen: boolean;
  activeTab: SettingsTabKey;
  openModal: (tab?: SettingsTabKey) => void;
  closeModal: () => void;
  setActiveTab: (tab: SettingsTabKey) => void;
}

export const useSettingsModalStore = create<SettingsModalState>((set) => ({
  isOpen: false,
  activeTab: 'general',
  openModal: (tab = 'general') => set({ isOpen: true, activeTab: tab }),
  closeModal: () => set({ isOpen: false }),
  setActiveTab: (tab) => set({ activeTab: tab }),
}));
