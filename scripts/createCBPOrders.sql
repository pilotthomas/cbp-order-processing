USE [MAS_PTL];
GO

CREATE TABLE dbo.CBPOrders (
	-- Primary key
    Id BIGINT IDENTITY(1,1) NOT NULL
        CONSTRAINT PK_CBPOrders PRIMARY KEY,
    -- Order Identifiers & Status
    CBPCommerceOrderId VARCHAR(50) NULL,
    CBPSapOrderId VARCHAR(50) NULL,
    CBPOrderSource VARCHAR(50) NULL,

	--Rosetta
	ExtSourceID VARCHAR(100) NULL,
	SalesOrderNo VARCHAR(50)  NULL,
	CustomerID            VARCHAR(100) NULL,
    ARDivisionNo          VARCHAR(20)  NULL,
    CustomerNo            VARCHAR(50)  NULL,
    DestinationID         VARCHAR(100) NULL,
    ShipToCode            VARCHAR(50)  NULL, ---Need to find ShipToCode
    ShipExpireDate        DATE         NULL,
    TaxSchedule           VARCHAR(50)  NULL,
    TicketClass           VARCHAR(50)  NULL,
    CustomerPONo          VARCHAR(100) NULL,

    -- Dates
	CBPOrderDate DATE NULL,
	CBPOrderModifiedDate DATE NULL,
	CBPPurchaseOrderDate DATE NULL,
	CBPEstimatedDeliveryDate DATE NULL,
	CBPRequestedDeliveryDate DATE NULL,

	-- Contact & Delivery Info
	CBPContactName VARCHAR(100) NULL,
	CBPContactPhoneNumber VARCHAR(50) NULL,
	CBPCustomerAccountNumber VARCHAR(50) NULL,
	CBPContactEmailAddress VARCHAR(100) NULL,
	CBPDeliveryInstructions VARCHAR(MAX) NULL,
	CBPDeliveryMethod VARCHAR(10) NULL,
	CBPIsRushDelivery BIT NULL,
	CBPIsRushOrder VARCHAR(50) NULL,
	CBPBlanketPo VARCHAR(50) NULL,

    -- Customer Location Details
    CBPCustomerCity VARCHAR(100) NULL,
    CBPCustomerCountry VARCHAR(100) NULL,
    CBPCustomerName VARCHAR(200) NULL,
    CBPCustomerNumber VARCHAR(50) NULL,
    CBPCustomerPostalCode VARCHAR(20) NULL,
    CBPCustomerState VARCHAR(100) NULL,
    CBPCustomerStreetNumber VARCHAR(200) NULL,

    -- Restriction Data
    CBPNewLineItemAllowed BIT NULL,
    CBPOnContract BIT NULL,
    CBPPartialUploadAllowed BIT NULL,
    CBPPodFileRequired BIT NULL,
    CBPPrefillMustExist BIT NULL,
    CBPSoldtoExist BIT NULL,

    -- Fulfilled By Details
    CBPFulfilledByCity VARCHAR(100) NULL,
    CBPFulfilledByCountry VARCHAR(100) NULL,
    CBPFulfilledByAddress VARCHAR(MAX) NULL,
    CBPFulfilledByAddressNumber VARCHAR(50) NULL,
    CBPFulfilledByState VARCHAR(100) NULL,
    CBPFulfilledByStreetNumber VARCHAR(200) NULL,

    -- Processing status
    OrderStatus           VARCHAR(50)  NULL,
    OrderInvoiceStatus    VARCHAR(50)  NULL,
    OrderCreatedAt        DATETIME2    NULL,
    OrderUpdatedAt        DATETIME2    NULL,
	ErrorDescription VARCHAR(MAX) NULL,

    OrderInvoiceStatusCreatedAt  DATETIME2 NULL,
    OrderInvoiceStatusUpdatedAt  DATETIME2 NULL,

	CBPOrderStatus	 VARCHAR(50)  NULL,
	CBPOrderInvoiceStatus VARCHAR(50)  NULL,
	CBPCreatedDate	 DATETIME2    NULL,
	CBPUpdatedDate	 DATETIME2    NULL
);
GO

CREATE TABLE dbo.CBPOrderItems (
    Id INT IDENTITY(1,1) PRIMARY KEY,
	CBPOrderId BIGINT NOT NULL,
	SalesOrderNo VARCHAR(50)  NULL,
    CBPCommerceOrderId VARCHAR(50) NULL,
    CBPSapOrderId VARCHAR(50) NULL,
    CBPPONumber VARCHAR(100) NULL,
	ItemCode VARCHAR(100) NULL,
	WarehouseCode VARCHAR(50) NULL,

    -- Consignment Details
    CBPConsignmentCode VARCHAR(50) NULL,
    CBPConsignmentSequenceNumber VARCHAR(10) NULL,
    CBPDefaultScheduledDeliveryDate DATE NULL,
    CBPDeliveryReceipt VARCHAR(50) NULL,
    CBPIsAcknowledgementOverdue BIT NULL,
    CBPIsDeliveryOverdue BIT NULL,
    CBPConsignmentStatus VARCHAR(50) NULL,
    CBPScheduledDeliveryDate DATE NULL,
	CBPActualDeliveryDate DATE NULL,

    -- Entry / Line Item Details
    CBPEntryNumber INT NULL,
    CBPProductCode VARCHAR(50) NULL, -- Corresponds to entry "code"
    CBPBaseProductName VARCHAR(200) NULL,
    CBPMaxDeliveryQuantity DECIMAL(18,2) NULL,
    CBPNewLineItem BIT NULL,
    CBPOrderedQty DECIMAL(18,2) NULL,
	CBPDeliveredQty DECIMAL(18,2) NULL,
    CBPPackageType VARCHAR(50) NULL,
    CBPPackagingName VARCHAR(200) NULL,
    CBPShipmentType VARCHAR(50) NULL,
    CBPUnit VARCHAR(20) NULL,


	OrderCreatedAt DATETIME2 NOT NULL
        CONSTRAINT DF_CBPOrderItems_CreatedAt
        DEFAULT SYSUTCDATETIME(),

    OrderUpdatedAt DATETIME2 NULL,

	CBPCreatedDate	 DATETIME2    NULL,
	CBPUpdatedDate	 DATETIME2    NULL,

    CONSTRAINT FK_CBPOrderItems_CBPOrders
        FOREIGN KEY (CBPOrderId)
        REFERENCES dbo.CBPOrders(Id),

    CONSTRAINT CK_CBPOrderItems_OrderedQty
        CHECK (CBPOrderedQty > 0)
);
GO
