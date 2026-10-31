// shadcn/ui-style Tabs built on Radix (keyboard accessible: arrow keys move between tabs).
import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List ref={ref} className={cn("flex w-full gap-1 border-b border-slate-200 bg-white px-2", className)} {...props} />
));
TabsList.displayName = "TabsList";

export const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "min-h-[44px] flex-1 border-b-2 border-transparent px-3 text-sm font-medium text-slate-600 transition-colors",
      "hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600",
      "data-[state=active]:border-brand-700 data-[state=active]:text-brand-900",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = "TabsTrigger";

export const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content ref={ref} className={cn("p-3 focus-visible:outline-none", className)} {...props} />
));
TabsContent.displayName = "TabsContent";
