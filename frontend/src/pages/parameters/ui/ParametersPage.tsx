import { ParameterForms } from '@/features/manage-parameters/ui/ParameterForms';
import { ParametersCatalog } from '@/widgets/parameters-catalog/ui/ParametersCatalog';

export const ParametersPage = () => (
  <div className="grid">
    <ParameterForms />
    <ParametersCatalog />
  </div>
);