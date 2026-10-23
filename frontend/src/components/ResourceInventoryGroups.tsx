import type { ReactNode } from "react";
import type { OperationalUnit, VehicleProfile } from "../types";
import { Box, Typography } from "./ui";

type Category = "terrestrial" | "aerial";

export function vehicleCategory(vehicle: VehicleProfile): Category {
  return vehicle.vehicle_class === "aircraft" ? "aerial" : "terrestrial";
}

export function unitCategory(unit: OperationalUnit, vehicles: VehicleProfile[]): Category {
  const vehicle = vehicles.find((value) => value.id === unit.vehicle_id);
  return vehicle
    ? vehicleCategory(vehicle)
    : unit.import_provenance?.category === "meios_aereos" ? "aerial" : "terrestrial";
}

export function ResourceInventoryGroups<T extends { import_provenance?: unknown }>({
  items, category, renderItem,
}: {
  items: T[];
  category: (item: T) => Category;
  renderItem: (item: T) => ReactNode;
}) {
  return <Box className="ds-stack">
    {items.some((item) => item.import_provenance) && <Typography as="p" variant="small">
      Os registos do Fogos.pt são provisórios, criados a partir dos totais comunicados. Confirme os indicativos,
      a localização e a disponibilidade. As unidades começam indisponíveis até confirmação.
    </Typography>}
    {(["terrestrial", "aerial"] as const).map((kind) => {
      const values = items.filter((item) => category(item) === kind);
      return <Box key={kind} className="ds-stack">
        <Typography as="h3" variant="h3">{kind === "aerial" ? "Meios aéreos" : "Meios terrestres"} ({values.length})</Typography>
        {values.map(renderItem)}
      </Box>;
    })}
  </Box>;
}
