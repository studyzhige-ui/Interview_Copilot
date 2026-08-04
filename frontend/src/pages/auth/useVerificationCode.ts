import { useEffect, useRef, useState } from 'react';
import { sendVerificationCode, type CodePurpose } from '@/api/auth';
import { sendCodeErr } from '@/lib/errors';
import { toast } from '@/store/uiStore';

export function useVerificationCode() {
  const [sending, setSending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const tickRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
  }, []);

  const startCooldown = (seconds: number) => {
    setCooldown(seconds);
    if (tickRef.current !== null) window.clearInterval(tickRef.current);
    tickRef.current = window.setInterval(() => {
      setCooldown((current) => {
        if (current <= 1) {
          if (tickRef.current !== null) window.clearInterval(tickRef.current);
          tickRef.current = null;
          return 0;
        }
        return current - 1;
      });
    }, 1000);
  };

  const send = async (email: string, purpose: CodePurpose, successMessage: string) => {
    setSending(true);
    try {
      const result = await sendVerificationCode(email.trim(), purpose);
      toast.success(successMessage);
      startCooldown(result.expires_in > 0 ? Math.min(result.expires_in, 60) : 60);
    } catch (error) {
      toast.error(sendCodeErr(error));
    } finally {
      setSending(false);
    }
  };

  return { sending, cooldown, send };
}
