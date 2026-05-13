import { Modal } from './Modal';
import { Btn } from './Btn';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  danger,
  onConfirm,
  onCancel,
  loading,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      width={420}
      footer={
        <>
          <Btn kind="ghost" onClick={onCancel} disabled={loading}>{cancelText}</Btn>
          <Btn
            kind={danger ? 'danger' : 'primary'}
            onClick={onConfirm}
            loading={loading}
          >
            {confirmText}
          </Btn>
        </>
      }
    >
      {description && (
        <div className="text-sm text-stone-600 leading-relaxed">{description}</div>
      )}
    </Modal>
  );
}
