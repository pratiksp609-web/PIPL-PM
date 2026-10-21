import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export interface Option { value: number; label: string }

export function useProjectOptions(includeArchived = false) {
  return useQuery({
    queryKey: ['project-options', includeArchived],
    queryFn: () => api.get('/api/projects', { page_size: 200, sort: 'code', include_archived: includeArchived }),
    select: (d: any) => (d.items as any[]).map((p) => ({ value: p.id, label: `${p.code} · ${p.name}`, currency: p.currency, client_id: p.client_id })),
    staleTime: 30_000,
  })
}

export function useClientOptions() {
  return useQuery({
    queryKey: ['client-options'],
    queryFn: () => api.get('/api/clients', { page_size: 200 }),
    select: (d: any) => (d.items as any[]).map((c) => ({ value: c.id, label: c.company_name })),
    staleTime: 30_000,
  })
}

export function useUserOptions() {
  return useQuery({
    queryKey: ['user-options'],
    queryFn: () => api.get('/api/users'),
    select: (d: any) => (d.items as any[]).map((u) => ({ value: u.id, label: u.full_name, role: u.role })),
    staleTime: 60_000,
  })
}

export function useSupplierOptions() {
  return useQuery({
    queryKey: ['supplier-options'],
    queryFn: () => api.get('/api/suppliers', { page_size: 200 }),
    select: (d: any) => (d.items as any[]).map((s) => ({ value: s.id, label: s.name })),
    staleTime: 30_000,
  })
}
