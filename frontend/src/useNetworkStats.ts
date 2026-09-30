import { useCallback, useEffect, useState } from "react";

import { fetchNetworkStats, fetchTaoUsd } from "./api";

export function useNetworkStats() {
  const [regTao, setRegTao] = useState<number | null>(null);
  const [alphaTao, setAlphaTao] = useState<number | null>(null);
  const [taoUsd, setTaoUsd] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      setRefreshing(true);
    }
    try {
      const taoPromise = fetchTaoUsd(refresh).then((price) => {
        if (price != null) {
          setTaoUsd(price);
        }
        return price;
      });
      const stats = await fetchNetworkStats(refresh);
      if (stats) {
        setRegTao(stats.reg_tao);
        if (stats.alpha_tao != null) {
          setAlphaTao(stats.alpha_tao);
        }
        if (stats.tao_usd != null) {
          setTaoUsd(stats.tao_usd);
        }
      }
      await taoPromise;
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    regTao,
    alphaTao,
    taoUsd,
    refreshing,
    refreshPrices: () => {
      void load(true);
    },
  };
}
