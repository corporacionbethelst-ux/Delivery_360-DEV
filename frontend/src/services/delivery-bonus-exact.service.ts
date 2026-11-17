import { api } from "@/lib/api";
import { capturePrivateTask } from "@/lib/private-task";
import {
  bonusOrderIds,
  normalizeBonusRecords,
} from "@/lib/delivery-bonus-exact";
export const deliveryBonusService = {
  read: async (values: string[], actor: { user_id: string; role: string }) => {
    const ids = bonusOrderIds([...values]),
      identity = { ...actor },
      task = capturePrivateTask();
    const result = await api.get<unknown>("/deliveries/bonuses/exact", {
      params: { order_ids: ids.join(",") },
    });
    task.assertCurrent();
    return normalizeBonusRecords(result, ids, identity);
  },
};
