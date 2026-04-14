import React, { createContext, useContext, useMemo, useState } from 'react';

const STORAGE_KEY = 'wareed_preview_leads_v1';

const PreviewLeadsContext = createContext(null);

function readStoredLeads() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistLeads(leads) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(leads));
  } catch {
    // Preview-only persistence; ignore localStorage failures.
  }
}

function buildLeadId() {
  const random = Math.random().toString(36).slice(2, 9);
  return `lead_${Date.now()}_${random}`;
}

export function PreviewLeadsProvider({ children }) {
  const [leads, setLeads] = useState(() => readStoredLeads());

  const addLead = (leadInput) => {
    const lead = {
      id: buildLeadId(),
      status: 'NEW',
      ...leadInput,
    };
    setLeads((prev) => {
      const next = [lead, ...prev];
      persistLeads(next);
      return next;
    });
    return lead;
  };

  const updateLeadStatus = (leadId, status) => {
    setLeads((prev) => {
      const next = prev.map((lead) => (lead.id === leadId ? { ...lead, status } : lead));
      persistLeads(next);
      return next;
    });
  };

  const clearLeads = () => {
    setLeads([]);
    persistLeads([]);
  };

  const value = useMemo(
    () => ({
      leads,
      addLead,
      updateLeadStatus,
      clearLeads,
      newLeadsCount: leads.filter((lead) => lead.status === 'NEW').length,
    }),
    [leads]
  );

  return <PreviewLeadsContext.Provider value={value}>{children}</PreviewLeadsContext.Provider>;
}

export function usePreviewLeads() {
  const context = useContext(PreviewLeadsContext);
  if (!context) {
    throw new Error('usePreviewLeads must be used within PreviewLeadsProvider');
  }
  return context;
}
